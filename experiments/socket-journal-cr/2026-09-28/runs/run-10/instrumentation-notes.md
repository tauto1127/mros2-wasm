# run-10 discovery probe

Observational instrumentation only. Functional control flow is unchanged. Added one-line `DISCOVERY_PROBE` events at:

- local SEDP publication/subscription change creation
- SPDP remote builtin endpoint capability processing
- SEDP builtin writer reader-proxy addition
- SEDP builtin writer `progress()` begin/end with history and next sequence number

The probe itself can perturb thread timing, so a success/failure difference is evidence about ordering but not by itself proof of the original uninstrumented race.
