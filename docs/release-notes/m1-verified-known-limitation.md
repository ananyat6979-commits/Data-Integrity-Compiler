# m1-verified known limitation

The `m1-verified` tag is preserved as the historical M1 snapshot. It has a known join-key configuration limitation: contract validation accepts any schema-valid key, while daily aggregation remains grouped by pickup location. Selecting a different valid key can therefore produce misleading stage semantics. The tag has not been rewritten. The M1.1 implementation rejects keys other than `PULocationID` until join-key semantics and aggregation are redesigned together.

The tag demonstrates the recorded duplicate-lookup fault and its observed row and aggregate impact. It does not establish detection recall, a low false-alarm rate, broad root-cause accuracy, or support for arbitrary join keys.
