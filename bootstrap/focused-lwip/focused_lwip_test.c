#include <arpa/inet.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sched.h>
#include <sys/socket.h>
#include <sys/types.h>
#include "cmsis_os.h"
#include "lwipopts.h"
#include "lwip/udp.h"
#include "netif_wasm_add.h"
#include "netif_wasm_get.h"
#include "udp_multicast_manager.h"

extern struct netif *netif_default;
extern void lwip_test_thread_udp_recv(void *argument);

static _Atomic int socket_calls, connect_calls, name_calls, close_calls;
static _Atomic int fail_socket, fail_connect, fail_name, bad_family, any_address;
static _Atomic uint32_t probe_address;
static _Atomic int active_probes, max_active_probes, block_connect, connect_entered, release_connect;
static _Atomic int force_lock_error;
static _Atomic int recv_calls, second_recv_errno;
static _Atomic int snapshot_started, snapshot_finished, snapshot_ok;
static _Atomic uint32_t expected_snapshot_ip, expected_snapshot_mask;
static int expected_recv_probe_calls, expected_recv_close_calls;
static int expected_recv_busy, expected_recv_lock_error;
static const char *expected_recv_ip;
static UdpMcInfoType mock_mcp;
static void check_snapshot(const char *ip, const char *mask);

static void check(int condition, const char *message)
{
  if (!condition) {
    fprintf(stderr, "FAIL: %s\n", message);
    exit(1);
  }
}

static void reset_probe_counts(void)
{
  atomic_store(&socket_calls, 0);
  atomic_store(&connect_calls, 0);
  atomic_store(&name_calls, 0);
  atomic_store(&close_calls, 0);
}

int test_netif_socket(int domain, int type, int protocol)
{
  (void)domain; (void)type; (void)protocol;
  atomic_fetch_add(&socket_calls, 1);
  if (atomic_load(&fail_socket)) {
    errno = EMFILE;
    return -1;
  }
  return 73;
}

int test_netif_connect(int fd, const struct sockaddr *address, socklen_t length)
{
  (void)fd; (void)address; (void)length;
  atomic_fetch_add(&connect_calls, 1);
  int active = atomic_fetch_add(&active_probes, 1) + 1;
  int max = atomic_load(&max_active_probes);
  while (active > max && !atomic_compare_exchange_weak(&max_active_probes, &max, active)) {}
  if (atomic_load(&block_connect)) {
    atomic_store(&connect_entered, 1);
    while (!atomic_load(&release_connect)) sched_yield();
  }
  atomic_fetch_sub(&active_probes, 1);
  if (atomic_load(&fail_connect)) {
    errno = ECONNREFUSED;
    return -1;
  }
  return 0;
}

int test_netif_getsockname(int fd, struct sockaddr *address, socklen_t *length)
{
  (void)fd;
  atomic_fetch_add(&name_calls, 1);
  if (atomic_load(&fail_name)) {
    errno = EIO;
    return -1;
  }
  struct sockaddr_in *local = (struct sockaddr_in *)address;
  memset(local, 0, sizeof(*local));
  local->sin_family = atomic_load(&bad_family) ? AF_INET6 : AF_INET;
  local->sin_addr.s_addr = atomic_load(&any_address) ? htonl(INADDR_ANY) : atomic_load(&probe_address);
  if (length) *length = sizeof(*local);
  return 0;
}

int test_netif_close(int fd)
{
  check(fd == 73, "close receives opened probe fd");
  atomic_fetch_add(&close_calls, 1);
  return 0;
}

int test_core_trylock(pthread_mutex_t *mutex)
{
  if (atomic_load(&force_lock_error)) return EINVAL;
  return pthread_mutex_trylock(mutex);
}

ssize_t test_udp_recvfrom(int fd, void *buffer, size_t length, int flags,
                          struct sockaddr *address, socklen_t *address_length)
{
  (void)fd; (void)buffer; (void)length; (void)flags; (void)address; (void)address_length;
  int call = atomic_fetch_add(&recv_calls, 1);
  if (call == 0) {
    errno = EINTR;
    return -1;
  }
  atomic_store(&second_recv_errno, errno);
  check(errno == EINTR, "actual UDP loop restores original errno before next recv");
  check(atomic_load(&socket_calls) == expected_recv_probe_calls,
        "EINTR branch makes exactly the expected coordinator probe attempt");
  check(atomic_load(&close_calls) == expected_recv_close_calls,
        "EINTR probe cleanup closes expected descriptor count");
  if (expected_recv_busy) {
    check(sys_trylock_tcpip_core() == EBUSY,
          "receive BUSY loser leaves another core owner untouched");
  } else if (expected_recv_lock_error) {
    atomic_store(&force_lock_error, 0);
    check(sys_trylock_tcpip_core() == 0,
          "failed trylock acquisition did not spuriously unlock core");
    sys_unlock_tcpip_core();
  }
  if (expected_recv_ip != NULL) check_snapshot(expected_recv_ip, "255.255.254.0");
  puts("RECEIVE_EINTR_CASE_PASS");
  exit(0);
  return -1;
}

UdpMcInfoType *udp_mc_info_get(void *pcb)
{
  (void)pcb;
  return &mock_mcp;
}

struct pbuf *pbuf_alloc(pbuf_layer layer, u16_t length, pbuf_type type)
{
  (void)layer; (void)length; (void)type;
  return NULL;
}

uint32_t osKernelGetTickCount(void) { return 1234; }
osStatus_t osDelay(uint32_t ticks) { (void)ticks; return osOK; }

static int refresh_thread_result;
static void *refresh_thread(void *unused)
{
  (void)unused;
  refresh_thread_result = netif_wasm_refresh();
  return NULL;
}

static void *snapshot_thread(void *unused)
{
  (void)unused;
  static netif_wasm_ip_snapshot_t snapshot;
  atomic_store(&snapshot_started, 1);
  int result = netif_wasm_get_ip_snapshot(&snapshot);
  atomic_store(&snapshot_ok, result == 0 && snapshot.valid &&
                             snapshot.ip_addr == atomic_load(&expected_snapshot_ip) &&
                             snapshot.netmask == atomic_load(&expected_snapshot_mask));
  atomic_store(&snapshot_finished, 1);
  return NULL;
}

static uint32_t parse_ip(const char *text)
{
  struct in_addr address;
  check(inet_pton(AF_INET, text, &address) == 1, "test IP parses");
  return address.s_addr;
}

static void set_route(const char *ip)
{
  atomic_store(&probe_address, parse_ip(ip));
}

static void check_snapshot(const char *ip, const char *mask)
{
  netif_wasm_ip_snapshot_t snapshot;
  check(netif_wasm_get_ip_snapshot(&snapshot) == 0, "copied snapshot succeeds");
  check(snapshot.valid, "snapshot validity follows default netif");
  check(snapshot.ip_addr == parse_ip(ip), "snapshot IP matches published route");
  check(snapshot.netmask == parse_ip(mask), "snapshot mask matches published route");
}

static void check_core_available(const char *message)
{
  int result = sys_trylock_tcpip_core();
  check(result == 0, message);
  sys_unlock_tcpip_core();
}

int main(int argc, char **argv)
{
  netif_wasm_ip_snapshot_t snapshot;
  pthread_t thread;
  struct netif *identity;

  check(sys_trylock_tcpip_core() == 0,
        "statically initialized production core mutex works before MX init");
  sys_unlock_tcpip_core();
  check(netif_default == NULL, "default netif starts explicitly invalid");
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_FAILED,
        "refresh before startup fails without synthesizing a netif");
  check(atomic_load(&socket_calls) == 0, "pre-start refresh does not probe");
  check(netif_wasm_get_ip_snapshot(&snapshot) == 0 && !snapshot.valid &&
        snapshot.ip_addr == 0 && snapshot.netmask == 0,
        "uninitialized copied snapshot is invalid and zeroed");

  check(netif_wasm_add(NULL, "bad-mask") == NETIF_WASM_REFRESH_FAILED,
        "invalid startup mask fails");
  check(atomic_load(&socket_calls) == 0, "invalid mask has no probe side effect");
  atomic_store(&fail_socket, 1);
  check(netif_wasm_add(NULL, "255.255.255.0") == NETIF_WASM_REFRESH_FAILED,
        "startup socket error fails");
  atomic_store(&fail_socket, 0);
  check(netif_default == NULL && atomic_load(&close_calls) == 0,
        "socket failure does not publish or close unopened descriptor");
  check_core_available("startup socket failure releases core");

  atomic_store(&fail_connect, 1);
  check(netif_wasm_add(NULL, "255.255.255.0") == NETIF_WASM_REFRESH_FAILED,
        "startup connect error fails");
  atomic_store(&fail_connect, 0);
  check(netif_default == NULL && atomic_load(&close_calls) == 1,
        "startup connect failure closes opened descriptor exactly once");
  check_core_available("startup connect failure releases core");
  atomic_store(&fail_name, 1);
  check(netif_wasm_add(NULL, "255.255.255.0") == NETIF_WASM_REFRESH_FAILED,
        "startup getsockname error fails");
  atomic_store(&fail_name, 0);
  check(netif_default == NULL && atomic_load(&close_calls) == 2,
        "startup getsockname failure closes exactly once and leaves default null");

  set_route("10.20.30.3");
  check(netif_wasm_add(NULL, "255.255.255.0") == 0,
        "startup publishes successful route");
  identity = netif_default;
  check(identity != NULL, "startup default netif is published");
  check_snapshot("10.20.30.3", "255.255.255.0");
  sys_lock_tcpip_core();
  netif_wasm_get_ip_snapshot_core_locked(&snapshot);
  check(snapshot.valid && snapshot.ip_addr == parse_ip("10.20.30.3"),
        "already-core-held getter copies while core mutex is owned");
  check(sys_trylock_tcpip_core() == EBUSY,
        "already-core-held getter does not recursively acquire or release core");
  sys_unlock_tcpip_core();

  set_route("10.20.30.3");
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_UNCHANGED,
        "same route returns UNCHANGED");
  check_snapshot("10.20.30.3", "255.255.255.0");
  set_route("10.20.30.6");
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_CHANGED,
        "new route returns CHANGED");
  check(netif_default == identity, "refresh preserves default object identity");
  check_snapshot("10.20.30.6", "255.255.255.0");

  reset_probe_counts();
  sys_lock_tcpip_core();
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_BUSY,
        "ordinary core owner yields BUSY");
  check(atomic_load(&socket_calls) == 0 && atomic_load(&connect_calls) == 0,
        "BUSY never probes");
  check(sys_trylock_tcpip_core() == EBUSY, "BUSY path never unlocks owner mutex");
  sys_unlock_tcpip_core();

  atomic_store(&force_lock_error, 1);
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_FAILED,
        "non-EBUSY core trylock error maps to FAILED");
  atomic_store(&force_lock_error, 0);
  check(atomic_load(&socket_calls) == 0,
        "failed lock acquisition returns before any probe");
  check_core_available("failed lock acquisition is not spuriously unlocked");

  atomic_store(&fail_socket, 1);
  reset_probe_counts();
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_FAILED,
        "socket failure maps to FAILED");
  atomic_store(&fail_socket, 0);
  check(atomic_load(&close_calls) == 0,
        "socket failure does not close unopened descriptor");
  check_snapshot("10.20.30.6", "255.255.255.0");
  check_core_available("refresh socket error releases owner mutex");

  atomic_store(&fail_connect, 1);
  reset_probe_counts();
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_FAILED,
        "connect failure maps to FAILED");
  atomic_store(&fail_connect, 0);
  check(atomic_load(&close_calls) == 1, "refresh connect error closes once");
  check_snapshot("10.20.30.6", "255.255.255.0");
  check_core_available("refresh connect error releases owner mutex");

  atomic_store(&fail_name, 1);
  reset_probe_counts();
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_FAILED,
        "getsockname error maps to FAILED");
  atomic_store(&fail_name, 0);
  check(atomic_load(&close_calls) == 1, "refresh getsockname error closes once");
  check_snapshot("10.20.30.6", "255.255.255.0");
  check_core_available("refresh getsockname error releases owner mutex");

  atomic_store(&bad_family, 1);
  reset_probe_counts();
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_FAILED,
        "non-IPv4 getsockname result rejected");
  atomic_store(&bad_family, 0);
  check(atomic_load(&close_calls) == 1,
        "invalid address family closes opened descriptor exactly once");
  atomic_store(&any_address, 1);
  reset_probe_counts();
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_FAILED,
        "ANY address getsockname result rejected");
  atomic_store(&any_address, 0);
  check(atomic_load(&close_calls) == 1,
        "ANY address rejection closes opened descriptor exactly once");
  check_snapshot("10.20.30.6", "255.255.255.0");

  atomic_store(&block_connect, 1);
  atomic_store(&connect_entered, 0);
  atomic_store(&release_connect, 0);
  set_route("10.20.30.7");
  check(pthread_create(&thread, NULL, refresh_thread, NULL) == 0,
        "start blocked probe owner");
  while (!atomic_load(&connect_entered)) sched_yield();
  int calls_before_loser = atomic_load(&socket_calls);
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_BUSY,
        "concurrent contender returns BUSY before second probe");
  check(atomic_load(&socket_calls) == calls_before_loser,
        "concurrent BUSY contender did not create a probe socket");
  atomic_store(&release_connect, 1);
  pthread_join(thread, NULL);
  atomic_store(&block_connect, 0);
  check(refresh_thread_result == NETIF_WASM_REFRESH_CHANGED,
        "sequential winner publishes after probe owner releases");
  check(atomic_load(&max_active_probes) == 1,
        "at most one concurrent probe ran");
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_UNCHANGED,
        "subsequent sequential winner is permitted and unchanged");
  check_snapshot("10.20.30.7", "255.255.255.0");

  atomic_store(&snapshot_started, 0);
  atomic_store(&snapshot_finished, 0);
  atomic_store(&snapshot_ok, 0);
  set_route("10.20.30.8");
  atomic_store(&expected_snapshot_ip, parse_ip("10.20.30.8"));
  atomic_store(&expected_snapshot_mask, parse_ip("255.255.254.0"));
  sys_lock_tcpip_core();
  check(pthread_create(&thread, NULL, snapshot_thread, NULL) == 0,
        "start ordinary snapshot accessor under held core");
  while (!atomic_load(&snapshot_started)) sched_yield();
  for (int i = 0; i < 1000; ++i) sched_yield();
  check(!atomic_load(&snapshot_finished),
        "ordinary snapshot waits for owner instead of reading torn fields");
  netif_default->ip_addr.addr = atomic_load(&expected_snapshot_ip);
  netif_default->netmask.addr = atomic_load(&expected_snapshot_mask);
  sys_unlock_tcpip_core();
  pthread_join(thread, NULL);
  check(atomic_load(&snapshot_ok), "ordinary snapshot returns coherent IP/mask");
  check_snapshot("10.20.30.8", "255.255.254.0");
  set_route("10.20.30.7");
  check(netif_wasm_refresh() == NETIF_WASM_REFRESH_CHANGED,
        "current IP refreshes after concurrent copied snapshot test");
  check_snapshot("10.20.30.7", "255.255.254.0");

  mock_mcp.sd = 23;
  reset_probe_counts();
  check_snapshot("10.20.30.7", "255.255.254.0");
  check(netif_default == identity, "default object identity remains stable");
  check(argc == 2, "run one receive case: busy|lock-failed|changed|unchanged|probe-failed");
  struct udp_pcb pcb = {0};
  atomic_store(&recv_calls, 0);
  atomic_store(&second_recv_errno, 0);
  reset_probe_counts();
  if (strcmp(argv[1], "busy") == 0) {
    expected_recv_busy = 1;
    sys_lock_tcpip_core();
  } else if (strcmp(argv[1], "lock-failed") == 0) {
    expected_recv_lock_error = 1;
    atomic_store(&force_lock_error, 1);
  } else if (strcmp(argv[1], "changed") == 0) {
    set_route("10.20.30.8");
    expected_recv_probe_calls = expected_recv_close_calls = 1;
    expected_recv_ip = "10.20.30.8";
  } else if (strcmp(argv[1], "unchanged") == 0) {
    expected_recv_probe_calls = expected_recv_close_calls = 1;
    expected_recv_ip = "10.20.30.7";
  } else if (strcmp(argv[1], "probe-failed") == 0) {
    atomic_store(&fail_name, 1);
    expected_recv_probe_calls = expected_recv_close_calls = 1;
    expected_recv_ip = "10.20.30.7";
  } else {
    check(0, "unknown receive case");
  }
  lwip_test_thread_udp_recv(&pcb);
  check(0, "receive mock must stop the actual loop after next recvfrom");
  return 1;
}
