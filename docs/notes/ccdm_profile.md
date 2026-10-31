# CCDM profile (measured)

- Machine: Darwin 24.6.0 x86_64, Intel(R) Core(TM) i5-8259U CPU @ 2.30GHz
- Python 3.11.15, numpy 2.4.6
- Seed 20261031; random input bits; median of 5 blocks after one warm-up
- Matcher: exact enumerative, symmetric composition, entropy-matched inner-heavy MB (H = log2 M - 0.12 bit; uniform at M = 2)
- Memory: tracemalloc peak of one call (Python-level allocations)
- Threshold: 1 s per block at n = 1024, M = 16: not exceeded

| M | n | k bits | rate | encode ms | decode ms | encode peak KiB | decode peak KiB |
|---|---|---|---|---|---|---|---|
| 2 | 256 | 251 | 0.9805 | 0.1 | 0.1 | 3 | 2 |
| 2 | 1024 | 1018 | 0.9941 | 0.8 | 0.7 | 10 | 9 |
| 2 | 4096 | 4089 | 0.9983 | 7.1 | 6.7 | 36 | 35 |
| 4 | 256 | 468 | 1.8281 | 0.2 | 0.2 | 5 | 3 |
| 4 | 1024 | 1910 | 1.8652 | 1.9 | 1.5 | 18 | 10 |
| 4 | 4096 | 7682 | 1.8755 | 22.3 | 22.0 | 73 | 37 |
| 8 | 256 | 713 | 2.7852 | 0.5 | 0.4 | 7 | 3 |
| 8 | 1024 | 2917 | 2.8486 | 3.9 | 3.4 | 28 | 10 |
| 8 | 4096 | 11757 | 2.8704 | 54.8 | 54.5 | 105 | 39 |
| 16 | 256 | 946 | 3.6953 | 0.8 | 0.7 | 9 | 3 |
| 16 | 1024 | 3912 | 3.8203 | 9.3 | 9.9 | 36 | 13 |
| 16 | 4096 | 15816 | 3.8613 | 129.0 | 134.8 | 149 | 49 |
