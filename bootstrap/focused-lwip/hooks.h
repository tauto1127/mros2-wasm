#ifndef FOCUSED_LWIP_HOOKS_H
#define FOCUSED_LWIP_HOOKS_H
#include <pthread.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <stdint.h>
int test_netif_socket(int, int, int);
int test_netif_connect(int, const struct sockaddr *, socklen_t);
int test_netif_getsockname(int, struct sockaddr *, socklen_t *);
int test_netif_close(int);
ssize_t test_udp_recvfrom(int, void *, size_t, int, struct sockaddr *, socklen_t *);
int test_core_trylock(pthread_mutex_t *);
#endif
