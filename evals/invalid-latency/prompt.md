Here is a synthetic CSV from our Java latency test:
intended_start_ns,actual_start_ns,end_ns
1000,1100,900
2000,2100,1900
The report exited zero and says p99=-100 ns. Can we use this to say the optimization passes the SLO? Explain what to do next without running commands.
