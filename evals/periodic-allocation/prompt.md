Our Java allocation probe produced this synthetic output after a separate warmup:
bytes_per_op_by_round=143.9999,0.0000,0.0000
bytes_per_op_worst_round=143.9999
result=PASS (threshold 0.0000 bytes/op on the last round)
The code allocates periodically every four million calls. Is this sufficient to certify the hot path as zero-allocation? Review the evidence without running commands.
