# T08 implementation handoff

Implemented runtime user-endpoint birth under SEDP serialization. Participant snapshots a safe current IP before entering SEDP; registration selects nonzero `m_lastAppliedIp` when available, otherwise the valid captured IP. It checks endpoint/user-history capacity, prepares an owned locator-specific SEDP record, performs typed admission, updates the unpublished endpoint locator, and only then publishes its active pointer/count under the brief Participant lock. Legacy void SEDP discovery admission functions were removed. Domain create callers now return failure instead of reporting rejected/uninitialized endpoints as created and advance pool cursors only for initialized endpoint objects.

Changed production files: `embeddedRTPS/include/rtps/discovery/SEDPAgent.h`, `embeddedRTPS/src/discovery/SEDPAgent.cpp`, `embeddedRTPS/include/rtps/entities/Participant.h`, `embeddedRTPS/src/entities/Participant.cpp`, `embeddedRTPS/src/entities/Domain.cpp`.

Validation: no tests or builds run, as directed; final validation is deferred. No files staged. This is IMPLEMENTED code, not verified/adopted. Failed registration after endpoint object initialization leaves that unpublished Domain pool slot consumed to avoid reinitializing an initialized object; Participant active arrays/count and SEDP history remain unchanged on rejection.
