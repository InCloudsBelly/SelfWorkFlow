# Ownership and invalidation

The earliest layer that owns both the data and its invariant owns the fix. Detection does not imply ownership. Compare persisted last-good and first-bad states, enumerate caches/recovery/temporary state, and rebuild every downstream artifact that consumed invalid data.
