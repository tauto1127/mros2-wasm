#ifndef MROS2_POSIX_NETIF_H
#define MROS2_POSIX_NETIF_H

#include <stddef.h>

/* Kept for source compatibility. netif_wasm_add() discovers the local
 * address at runtime and ignores this argument. */
#define NETIF_IPADDR NULL
#define NETIF_NETMASK "255.255.255.0"

#endif /* MROS2_POSIX_NETIF_H */
