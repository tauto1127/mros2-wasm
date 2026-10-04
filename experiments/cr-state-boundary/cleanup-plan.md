# C/R state-boundary experiment cleanup for Luna

対象 worktree:
`/home/osslab/20261004-mros2-wasm-cr-state-boundary`

対象 branch:
`experiment/cr-state-boundary`

目的:
1. 今回の state-boundary 実験の fresh verification 証跡を失わないようにGitへ固定する。
2. branch全体をユーザーnamespaceのremoteへpushする。
3. push成功とremote ref確認後に、このexperiment worktreeを削除する。

## 絶対条件

- push先は `origin` のみ。
- 現在の `origin` は `git@github.com:tauto1127/mros2-wasm.git` であることを実行直前に再確認する。
- `upstream` (`oss-fun`) には絶対にpushしない。
- force pushしない。
- `git clean` を使わない。
- integration worktreeを変更しない。
- worktree削除前に、唯一の実験証跡がuntrackedのまま残っていないことを確認する。
- unrelated/pre-existing dirty stateを勝手に修正・commitしない。
- Boost/WAMR submoduleのdirty stateや生成物は、必要な実験証跡でない限りcommitしない。
- worktree削除は最後。pushまたは証跡保全に失敗したら削除しない。

## 現状の重要情報

fresh verification時の基準commit:
`11e78503586aae6d728d35bf2b875917583aaa3a`

その後、branchはさらに進んでいる可能性がある。計画作成時点では:
`a086fd71d01fff506c7874e2c9710a6e22cf0e9e`

最近のcommitには以下が見えていた:
- `a086fd71 test: ignore ROS 2 campaign bytecode`
- `ad6c68fa test: add ROS 2 C/R interoperability campaign`
- `11e78503 test: document WAMR C/R state-boundary evidence`

fresh evidence:
`experiments/cr-state-boundary/results/fresh-20261004-01/`

このディレクトリは計画作成時点ではuntrackedだったため、削除前に必ず監査する。

主要report:
`experiments/cr-state-boundary/report.md`

manifest:
`experiments/cr-state-boundary/results/manifest.json`

## Step 1: 状態監査

まずread-onlyで:

```bash
cd /home/osslab/20261004-mros2-wasm-cr-state-boundary
git status --short --branch
git log --oneline --decorate -12
git remote -v
git submodule status --recursive
```

さらにfresh evidenceの一覧・サイズ・hashを確認する。

```bash
find experiments/cr-state-boundary/results/fresh-20261004-01 -type f -print | sort
```

before/after/summary、raw logs、result JSON、hash/checksum類を読む。

## Step 2: report/manifestにfresh verificationが反映済みか確認

`report.md` と `results/manifest.json` に、少なくとも以下が記録されているか確認する。

fresh same-IP:
- trial: `experimental-same-run-03`
- PASS
- pre/post roundtrip 10 consecutive
- guest sentinel preserved
- native sentinel = 0
- stored .3 / probed .3

fresh changed-IP:
- trial: `experimental-changed-run-01`
- PASS
- pre/post roundtrip 10 consecutive
- guest sentinel preserved
- native sentinel = 0
- first pre-mutation stored .3 / probed .6
- later stored .6

provenance:
- baseline commit `11e78503586aae6d728d35bf2b875917583aaa3a`
- before/after revision state
- artifact hashes
- Docker environment
- raw-log checksums
- changed-IP gate input provenance
- PASS後checkpoint imageはrunner既存挙動で削除されたが、事前inventory/hashは保存済みという説明

まだ反映されていなければ、既存raw evidenceを使ってreport/manifestだけ最小更新する。
新しい実験は実行しない。

## Step 3: fresh evidenceのcommit対象を決める

保存すべきもの:
- fresh verificationのsummary
- before/after provenance
- gate provenance
- result JSON
- raw logs（研究証跡として必要なもの）
- checksums/hash manifests
- report/manifestの必要な更新

原則保存しないもの:
- `__pycache__`
- 再生成可能なbuild directory全体
- runtime build output全体
- 一時checkpoint image
- compiler cacheなど

ただし既存repositoryの実験証跡保存方針を確認して合わせること。
「大きいから」という理由だけで、raw logなど唯一の一次証拠を落とさない。

`experiments/cr-state-boundary/plan.md` は実験実行計画として研究証跡に残す価値があるならcommitしてよい。重複・不要と判断するなら削除前にその理由をcleanup logに残す。

## Step 4: unrelated changeを混ぜない

`git status` の各項目について:
- 今回のstate-boundary/fresh verification由来
- 別実験（例: ROS2 interoperability）
- pre-existing dirty submodule
- generated artifact

に分類する。

すでにcommit済みの別実験commitをrewrite/revertしない。
未commitのunrelated source changeがあれば今回のcleanup commitへ混ぜない。

## Step 5: validation

commit前に:

```bash
git diff --check
python3 experiments/cr-state-boundary/test_campaign_parser.py
```

テスト実行方法がrepositoryでラッパー必須なら、既存reportに記録されたvalidated commandを使う。

fresh evidenceのJSONがparse可能なことも確認。

## Step 6: commit

fresh evidence/report/manifestに未commit変更がある場合のみ、小さいcommitを作る。

推奨message:
`test: preserve fresh C/R state-boundary verification`

必要ならcleanup metadata用にもう1 commitまで可。
無意味にcommitを細分化しない。

commit後:

```bash
git status --short --branch
git log --oneline --decorate -8
```

を保存。

## Step 7: push先の安全確認

必ず:

```bash
git remote get-url --push origin
```

が `github.com:tauto1127/` namespace であることを文字列で確認する。

想定:
`git@github.com:tauto1127/mros2-wasm.git`

異なる場合はSTOP。pushしない。

## Step 8: branch push

forceなしで:

```bash
git push -u origin experiment/cr-state-boundary
```

push後、remote refを確認:

```bash
git ls-remote --heads origin refs/heads/experiment/cr-state-boundary
git rev-parse HEAD
```

remote SHAとlocal HEADが一致すること。

この確認が取れなければworktree削除禁止。

## Step 9: deletion preflight

worktree削除直前に:
- 保存対象証跡がすべてcommit済み
- remote branchがlocal HEADと一致
- Gitに入れないuntracked filesのうち、唯一の研究証拠がない
- integration worktreeは無変更
- submodule dirty stateの内容をcleanup logへ記録済み

を確認。

cleanup logを残すなら、worktree内ではなくpush済みcommitに入れるか、親repo側の安全な場所に置く。
削除直前に新しい未pushファイルをworktreeへ作らない。

## Step 10: worktree削除

親repositoryからworktree一覧を確認:

```bash
git -C /home/osslab/mros2-wasm worktree list --porcelain
```

対象pathが正しいことを確認。

通常removeをまず試す:

```bash
git -C /home/osslab/mros2-wasm worktree remove /home/osslab/20261004-mros2-wasm-cr-state-boundary
```

dirty generated artifactsのため通常removeが拒否された場合:
1. 何が残っているか再確認。
2. unique evidenceがないことを確認。
3. branchがremoteへ完全push済みであることを再確認。
4. その条件を満たした場合のみ `--force` を使用してよい。

```bash
git -C /home/osslab/mros2-wasm worktree remove --force /home/osslab/20261004-mros2-wasm-cr-state-boundary
```

`rm -rf` で直接消さない。

## Step 11: final verification

```bash
git -C /home/osslab/mros2-wasm worktree list --porcelain
git -C /home/osslab/mros2-wasm branch --list experiment/cr-state-boundary
git -C /home/osslab/mros2-wasm ls-remote --heads origin refs/heads/experiment/cr-state-boundary
```

確認項目:
- experiment worktree pathが一覧から消えている
- local branchは残っていてよい
- remote branchが存在
- remote SHAが最終local branch SHAと一致

## Final report

最後に以下だけ報告:
- cleanup前HEAD
- fresh evidenceを追加commitしたか、そのcommit SHA
- 最終HEAD
- push先remote URL
- remote branch SHA
- worktree削除成功/失敗
- force removeを使ったか
- 削除前に残っていたuntracked/generated filesの扱い
- integration worktreeを変更していないこと
- pushしていないremote（upstream/oss-fun）
