---
created: 2026-09-30
last_updated: 2026-09-30
sources:
  - "mros2/include/mros2.h and mros2/src/mros2.cpp"
  - "mros2/embeddedRTPS/{include/rtps/common/Locator.h,include/rtps/discovery/TopicData.h,include/rtps/discovery/ParticipantProxyData.h,src/entities/Participant.cpp,src/discovery/SPDPAgent.cpp}"
  - "lwip-wasm/src/netif/netif_wasm.c,include/netif.h,lwip-wasm/src/include/lwipopts.h,lwip-wasm/lwip/src/include/lwip/netif.h"
  - "lwip-wasm/src/core/{udp.c,udp_multicast.c,udp_multicast.h}"
  - "third_party/wamr/core/iwasm/libraries/{lib-socket/src/wasi/wasi_socket_ext.c,libc-wasi/sandboxed-system-primitives/src/posix.c}"
  - "third_party/wamr/core/shared/platform/common/posix/posix_socket.c"
  - "experiments/socket-journal-cr/2026-09-27/runs/run-06/report.md"
---
# mROS 2 WasmではIPアドレス状態をどの層が保持するか

このリポジトリのWasm経路では、ROSからOSまで同じIPアドレス変数を共有しているわけではない。ROSのNodeラッパーにIPフィールドはなく、embeddedRTPSは送受信用locatorとしてIPのコピーを持つ。lwIPの`netif`は現在値を保持し、WAMRのsocket拡張はホストのsocket APIを通じて実行時のローカルアドレスを読み取る。従って、IPアドレスのコピーはDDSまで存在する一方、実際に使うローカルsocketアドレスを決める起点はホスト側のsocket経路にある。この最後の「OS側が起点」という説明は、リポジトリ内のPOSIX境界からの推定である。

## 層ごとの保持場所

| 層 | どこにあるか | 状態の性質 |
|---|---|---|
| ROSラッパー | `mros2::Node`には`node_name`と`rtps::Participant *part`がある | Node自身のIPコピーはない。下のDDSやネットワーク層を使う |
| DDS / embeddedRTPS | `FullLengthLocator`、endpointの`TopicData`、SPDP announcement buffer、相手participantのproxy | 実行時に生成・保持されるlocatorのコピー。netifを設定する正本ではない |
| lwIP | `netif_wasm.ip_addr`と`netif_default`。UDP PCBやmulticast管理情報にも関連値 | `netif`がlwIP側の現在IP。socketやIGMP用の値は別々にコピーされ、明示的な更新・再作成が必要 |
| WAMR WASI socket拡張 | WASI address構造体への変換とWAMR fd table | IPを独自に決めず、アドレスを渡し、socket上のローカルアドレスを返す境界 |
| ホストOS | WAMR POSIX実装が呼び出すhost socketのlocal address | `connect()`後の`getsockname()`が返す値の供給元。実際のinterface/routeの設定主体だという部分はコードからの推定 |

```mermaid
flowchart LR
  OS[ホストsocket / route<br/>getsocknameの応答] -->|実行時に読み取り| WASI[WAMR WASI socket拡張<br/>sock_addr_local]
  WASI -->|IPv4をコピー| NETIF[lwIP netif_wasm.ip_addr<br/>netif_default]
  NETIF -->|現在値を参照して生成| LOC[DDS FullLengthLocator<br/>endpoint / SPDPのコピー]
  LOC -->|SPDPで広告| PEER[remote participantがlocatorを保持]
```

図のOS層について、コードが直接示すのはWAMRのPOSIX socket実装がOSの`connect()`と`getsockname()`を呼ぶところまでである。ホストinterfaceの設定・route選択ロジックそのものはこのリポジトリにはないため、OSが環境側のアドレス状態を管理するという説明は、そのsocket境界とrun-06のDocker記録に基づく推定として扱う。

## ROSラッパーはIPを保持しない

`mros2::Node`の公開データメンバーは`node_name`と`rtps::Participant *part`で、IPアドレス用のメンバーはない（[`mros2/include/mros2.h` L43-L102](../../mros2/include/mros2.h#L43-L102)）。`Node::create_node()`はDomainからparticipantを作り、Nodeに格納する（[`mros2/src/mros2.cpp` L167-L192](../../mros2/src/mros2.cpp#L167-L192)）。Wasmアプリの例では`netif_wasm_add()`を`mros2::init()`より前に呼んでおり、IP初期化はROS Node生成より下のネットワーク準備として行われる（[`workspace/pub_twist/app.cpp` L13-L25](../../workspace/pub_twist/app.cpp#L13-L25)）。

ここでの結論は「このmROS 2ラッパーのNodeにIP状態はない」である。ROS topicやmessage payloadにIPが含まれるかを一般論として論じているのではなく、この実装が通信先を管理する方法を指している。

## DDSはlocatorとしてIPをコピーする

embeddedRTPSの`getLocalIpAddress()`は、その時点の`netif_default->ip_addr`を読み、`FullLengthLocator`を作る関数へ4 octetを渡す。`FullLengthLocator`自身はIPv4を16 byteのaddress配列とportに保持する（[`Locator.h` L50-L63, L111-L135](../../mros2/embeddedRTPS/include/rtps/common/Locator.h#L50-L63)）。このためlocatorはlwIPへの参照ではなく、生成時点のアドレスを含む値のコピーである。

各endpointの`TopicData`にも`unicastLocator`と`multicastLocator`が格納される。writer/reader生成時に`getUserUnicastLocator()`の戻り値が`TopicData`へ入るので、DDS endpointは作成時点のIP locatorを保持する（[`TopicData.h` L42-L65](../../mros2/embeddedRTPS/include/rtps/discovery/TopicData.h#L42-L65)、[`Domain.cpp` L392-L400, L449-L465](../../mros2/embeddedRTPS/src/entities/Domain.cpp#L392-L400)）。

SPDPでは、announcement用bufferと`ucdrBuffer`が`SPDPAgent`のメンバーとして存在する（[`SPDPAgent.h` L64-L73](../../mros2/embeddedRTPS/include/rtps/discovery/SPDPAgent.h#L64-L73)）。`addParticipantParameters()`はそのときのlocal unicast locatorを作ってbufferへシリアライズする（[`SPDPAgent.cpp` L390-L449](../../mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp#L390-L449)）。受信側もSPDPで受け取ったmetatraffic/default locatorを`ParticipantProxyData`の配列に保存するため、DDS内部には自分と相手のIP locatorコピーがある（[`ParticipantProxyData.h` L44-L60](../../mros2/embeddedRTPS/include/rtps/discovery/ParticipantProxyData.h#L44-L60)）。

IP変更時は、それらのコピーを更新する処理が別に必要になる。`Participant::refreshLocalLocators()`は新しいnetif値からlocatorを作り直し、user writer/readerの`m_attributes.unicastLocator`を更新してSEDPへ再登録する（[`Participant.cpp` L420-L448](../../mros2/embeddedRTPS/src/entities/Participant.cpp#L420-L448)）。`SPDPAgent::refreshLocalIp()`は`netif_wasm_refresh()`の変更通知を受けるとこれを呼び、announcement bufferも再構築する（[`SPDPAgent.cpp` L81-L105](../../mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp#L81-L105)）。定期broadcast workerは更新されたannouncementを送る（[`SPDPAgent.cpp` L109-L128](../../mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp#L109-L128)）。

この更新経路には範囲の注意がある。SEDPの組み込みendpoint用`TopicData` locatorはDomain初期化時に作られる（[`Domain.cpp` L201-L226](../../mros2/embeddedRTPS/src/entities/Domain.cpp#L201-L226)）一方、`refreshLocalLocators()`は`BUILD_IN_WRITER`/`BUILD_IN_READER`を明示的に除外し、user-defined endpointだけを書き換える（[`Participant.cpp` L425-L445](../../mros2/embeddedRTPS/src/entities/Participant.cpp#L425-L445)）。このtreeで確認したlocator代入箇所では、これら組み込み`TopicData`を更新する別経路は見つからなかった。そのため作成時IPのコピーが残る可能性があるが、移行時の実動作への影響は未確認である。SPDP participant announcementの再構築はこれとは別の更新経路である。

## lwIPはnetif値と複数のコピーを保持する

Wasm用netif実装は`static struct netif netif_wasm`を持ち、`netif_default`をそのnetifへ向ける。`netif_wasm_add()`はsocket probe結果を`netif_wasm.ip_addr`へ、引数のnetmaskを`netif_wasm.netmask`へ設定する（[`netif_wasm.c` L10-L16, L61-L81](../../lwip-wasm/src/netif/netif_wasm.c#L10-L16)）。lwIPの一般`struct netif`にもIPv4の`ip_addr`、`netmask`、`gw`フィールドが定義されており、`netif_default`はlwIPのglobal pointerとして公開される（[`netif.h` L257-L271, L409](../../lwip-wasm/lwip/src/include/lwip/netif.h#L257-L271)）。このWasm経路では`netif_wasm.ip_addr`がlwIP側の実行時IPコピーである。

IPを取得するたびに永久的なsocketを残すわけではない。`probe_local_ip()`はUDP socketを作り、discovery宛先へ`connect()`し、`getsockname()`で得たlocal IPv4を出力引数にコピーし、socketを閉じる（[`netif_wasm.c` L18-L58](../../lwip-wasm/src/netif/netif_wasm.c#L18-L58)）。その後`netif_wasm_add()`または`netif_wasm_refresh()`が値をnetifへ保存する。`refresh()`は既存netifのIPv4を更新し、変更通知を立てる。restore後に`netif_default == NULL`ならnetifを再初期化する（[`netif_wasm.c` L84-L125](../../lwip-wasm/src/netif/netif_wasm.c#L84-L125)）。

lwIPの中でも値は一箇所だけではない。`udp_bind()`は要求されたbind IPをUDP PCBの`local_ip`に保存し、multicast管理情報`UdpMcInfoType.local_ipaddr`にはnetifのIPをコピーする（[`udp.c` L223-L238](../../lwip-wasm/src/core/udp.c#L223-L238)）。`UdpMcInfoType`はこの値に加えてsocket descriptor、port、multicast interface requestを保持する（[`udp_multicast.h` L18-L25](../../lwip-wasm/src/core/udp_multicast.h#L18-L25)）。特にPCBの`local_ip`はbind要求値なので、`0.0.0.0`のようなANY bindの場合はnetifの具体的IPと同じ値とは限らない。

では、なぜこのWasm経路でもlwIPがIPを持つのか。embeddedRTPSは`netif_default->ip_addr`から自分のadvertisement locatorを作り（[`Locator.h` L111-L135](../../mros2/embeddedRTPS/include/rtps/common/Locator.h#L111-L135)）、同じsubnetかどうかの判定にもnetifのIPとnetmaskを使う（[`UdpDriver.cpp` L85-L88](../../mros2/embeddedRTPS/src/communication/UdpDriver.cpp#L85-L88)）。UDPのmulticast復旧では、netifのIPを`IP_ADD_MEMBERSHIP`のinterface指定に使う（[`udp_multicast.c` L27-L36, L105-L112](../../lwip-wasm/src/core/udp_multicast.c#L27-L36)）。さらにこのWasm向け`udp_sendto()`はlwIPのIP出力関数へ渡さず、pbufのpayloadをまとめてhost socketの`sendto()`へ渡し、`udp_bind_socket()`もhost socketを`INADDR_ANY`へbindする（[`udp.c` L62-L120, L145-L158](../../lwip-wasm/src/core/udp.c#L62-L120)）。したがって、この経路でnetifのIPが担う中心的な役割は、lwIPとDDSにローカルinterface情報を提供し、subnetやmulticast状態を管理することにある。実際の送信socketのsource addressとroute選択はhost socket側が行う。

receive socket復旧処理はnetifを再取得し、`local_ipaddr`を現在のnetif値へ更新し、古いsocketを閉じて再作成・bindし、保存していたmulticast groupへ再参加する（[`udp_multicast.c` L27-L62](../../lwip-wasm/src/core/udp_multicast.c#L27-L62)）。つまり`netif.ip_addr`を書き換えただけで既存socket descriptorやmulticast参加状態まで自動的に同じ値へ置き換わる設計ではなく、復旧関数でコピーとsocketを作り直している。

このWasm buildではDHCPは無効、AUTOIPも`LWIP_DHCP`に連動して無効である（[`lwipopts.h` L239-L251](../../lwip-wasm/src/include/lwipopts.h#L239-L251)）。したがってlwIPがDHCP leaseとしてIPを保持しているのではない。netmaskは初回に`NETIF_NETMASK`から渡す固定文字列であり、restore後の再初期化には`DEFAULT_NETMASK`が使われる（[`include/netif.h` L6-L9](../../include/netif.h#L6-L9)、[`netif_wasm.c` L10-L12, L95-L105](../../lwip-wasm/src/netif/netif_wasm.c#L10-L12)）。IPのprobeは実行時、DHCP/AUTOIPフラグとnetmask値はビルド時に組み込まれた設定である。

## WASI拡張はホストsocket境界

アプリ側の`connect()`は`struct sockaddr`をWASI addressに変換し、importされた`__wasi_sock_connect()`へ渡す（[`wasi_socket_ext.c` L177-L195](../../third_party/wamr/core/iwasm/libraries/lib-socket/src/wasi/wasi_socket_ext.c#L177-L195)、[`wasi_socket_ext.h` L375-L389](../../third_party/wamr/core/iwasm/libraries/lib-socket/inc/wasi_socket_ext.h#L375-L389)）。`getsockname()`もimportされた`__wasi_sock_addr_local()`からlocal addressを受け取り、`sockaddr`へ戻す（[`wasi_socket_ext.c` L377-L391](../../third_party/wamr/core/iwasm/libraries/lib-socket/src/wasi/wasi_socket_ext.c#L377-L391)、[`wasi_socket_ext.h` L227-L245](../../third_party/wamr/core/iwasm/libraries/lib-socket/inc/wasi_socket_ext.h#L227-L245)）。この互換層は値の形式を変換するが、netif IPを独自に割り当てる処理はしていない。

WAMR WASI host側はsocketを`os_socket_create()`で開き、戻ったhandleをWASI descriptor objectの`file_handle`へ格納する。common POSIX backendの`os_socket_create()`はOSの`socket()`を呼ぶ（[`posix.c` L316-L320, L661-L687, L2661-L2701](../../third_party/wamr/core/iwasm/libraries/libc-wasi/sandboxed-system-primitives/src/posix.c#L2661-L2701)、[`posix_socket.c` L118-L134](../../third_party/wamr/core/shared/platform/common/posix/posix_socket.c#L118-L134)）。`wasi_ssp_sock_connect()`はその`file_handle`を使って`blocking_op_socket_connect()`を呼ぶ（[`posix.c` L2518-L2548](../../third_party/wamr/core/iwasm/libraries/libc-wasi/sandboxed-system-primitives/src/posix.c#L2518-L2548)）。local address照会も同じhandleを`os_socket_addr_local()`へ渡す（[`posix.c` L2357-L2378](../../third_party/wamr/core/iwasm/libraries/libc-wasi/sandboxed-system-primitives/src/posix.c#L2357-L2378)）。

このWAMRのcommon POSIX backendでは、`os_socket_connect()`がhost `connect()`を呼び、`os_socket_addr_local()`がhost `getsockname()`の結果を返す（[`posix_socket.c` L232-L250, L1004-L1017](../../third_party/wamr/core/shared/platform/common/posix/posix_socket.c#L232-L250)）。このため、Wasm側のprobe結果はホストのsocket local endpointを読んだ値である。どのinterfaceやrouteが選ばれるか、container namespaceでどのIPが割り当てられているかはOS側環境に依存する。ただしOSのinterface設定を変更するコードはここにはなく、OSをアドレス決定の供給元とする点はsocket呼び出しからの推定である。

## restore時に残る状態と再取得

`netif_wasm_refresh()`のコメントには、WAMR restoreでnative globalが初期状態から再作成されるため、`netif_default == NULL`ならnetifオブジェクトを作り直す、と明記されている（[`netif_wasm.c` L95-L107](../../lwip-wasm/src/netif/netif_wasm.c#L95-L107)）。再作成では、その時点のsocket probe結果を入れ、`ip_changed_pending`を立てる。次のSPDP周期に`refreshLocalIp()`が通知を取り出すと、DDS locatorとannouncement bufferを再構築する（[`SPDPAgent.cpp` L81-L105](../../mros2/embeddedRTPS/src/discovery/SPDPAgent.cpp#L81-L105)）。

run-06では同一ホスト上のDocker移行先でlocal IPが`.3`から`.6`に変わった記録がある。レポートは`netif_wasm`の更新値と移行先containerの`172.18.0.6`が一致したとし、4つのUDP portのreceive socket復旧も記録している。一方、90秒ゲートの完全なアプリ往復は0件だった（[run-06 report L73-L86](2026-09-27/runs/run-06/report.md#L73-L86)、[L90-L102](2026-09-27/runs/run-06/report.md#L90-L102)）。従ってrun-06が直接裏付けるのは、復元先でのIP再取得・netif反映と受信socket復旧までである。DDS locator更新のコード経路は存在するが、この試験結果だけで移行後の双方向ROS通信全体が復旧したとは言えない。

## まとめ

- ROSラッパーのNodeにはIP状態がない。
- DDSはIPをlocatorとして複数のruntime copyに保存し、IP変更時に更新・再広告する。
- lwIPは`netif_default`が参照する`netif_wasm.ip_addr`を実行時の現在値として保持する。UDP/IGMP用には別コピーやsocket状態もある。
- WAMR WASI socket拡張はlocal IPを決めず、host socket APIへ処理を渡して結果を返す。
- このPOSIX経路ではホストsocketの`connect()`/`getsockname()`がIP取得元となる。interface/routeの管理主体をOSとする部分は、host API境界からの推定である。
- IPは実行時に取り直す一方、DHCP/AUTOIP無効や`/24` netmask、probe宛先はビルドに含まれる固定設定である。
