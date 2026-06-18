# Results

2026 May 05

## schema-registry-avro / field: json

```
━━━━━━━━━━ json ━━━━━━━━━━
  iterations         :     10,000
  encoded size       :      3,323 bytes   (baseline)
  encode avg         :       7.93 µs      (baseline)
  decode avg         :       6.91 µs      (baseline)
  encode p50/p95/p99 :       7.58 /     8.54 /    10.71 µs
  encode min/max/σ   :       6.96 /   194.25 /     3.38 µs
  decode p50/p95/p99 :       6.58 /     7.42 /     9.29 µs
  decode min/max/σ   :       6.12 /   164.25 /     3.17 µs
  throughput         : encode    126,164 ops/s | decode    144,803 ops/s
.
━━━━━━━━━━ msgpack ━━━━━━━━━━
  iterations         :     10,000
  encoded size       :      2,716 bytes   ( -18.3% vs json, 1.22x smaller)
  encode avg         :       3.87 µs      ( -51.1% vs json, 2.05x faster )
  decode avg         :       5.01 µs      ( -27.5% vs json, 1.38x faster )
  encode p50/p95/p99 :       3.62 /     4.79 /     5.92 µs
  encode min/max/σ   :       3.38 /   116.00 /     1.97 µs
  decode p50/p95/p99 :       4.71 /     6.17 /     7.25 µs
  decode min/max/σ   :       4.42 /   118.00 /     2.23 µs
  throughput         : encode    258,144 ops/s | decode    199,695 ops/s
.
━━━━━━━━━━ schema-registry-avro ━━━━━━━━━━
  iterations         :     10,000
  encoded size       :      2,533 bytes   ( -23.8% vs json, 1.31x smaller)
  encode avg         :      23.81 µs      (+200.4% vs json, 3.00x slower )
  decode avg         :      13.37 µs      ( +93.6% vs json, 1.94x slower )
  encode p50/p95/p99 :      24.17 /    25.46 /    31.96 µs
  encode min/max/σ   :      21.38 /    82.75 /     2.33 µs
  decode p50/p95/p99 :      13.58 /    14.25 /    17.83 µs
  decode min/max/σ   :      11.88 /    43.33 /     1.42 µs
  throughput         : encode     41,999 ops/s | decode     74,806 ops/s
.
═══════════════ Summary (baseline = json) ═══════════════
format                      size     Δsize    enc µs     Δenc    dec µs     Δdec     enc ops/s    dec ops/s
-----------------------------------------------------------------------------------------------------------
json                       3,323    (base)      7.93   (base)      6.91   (base)       126,164      144,803
msgpack                    2,716    -18.3%      3.87   -51.1%      5.01   -27.5%       258,144      199,695
schema-registry-avro       2,533    -23.8%     23.81  +200.4%     13.37   +93.6%        41,999       74,806
```

## schema-registry-avro / field: msgpack


```
━━━━━━━━━━ json ━━━━━━━━━━
  iterations         :     10,000
  encoded size       :      3,323 bytes   (baseline)
  encode avg         :       8.26 µs      (baseline)
  decode avg         :       7.08 µs      (baseline)
  encode p50/p95/p99 :       8.33 /     8.62 /    10.04 µs
  encode min/max/σ   :       7.17 /    21.79 /     0.56 µs
  decode p50/p95/p99 :       7.17 /     7.33 /     8.54 µs
  decode min/max/σ   :       6.21 /    29.88 /     0.50 µs
  throughput         : encode    121,010 ops/s | decode    141,196 ops/s
.
━━━━━━━━━━ msgpack ━━━━━━━━━━
  iterations         :     10,000
  encoded size       :      2,716 bytes   ( -18.3% vs json, 1.22x smaller)
  encode avg         :       3.85 µs      ( -53.4% vs json, 2.15x faster )
  decode avg         :       4.87 µs      ( -31.2% vs json, 1.45x faster )
  encode p50/p95/p99 :       3.92 /     4.08 /     4.92 µs
  encode min/max/σ   :       3.42 /    44.12 /     0.58 µs
  decode p50/p95/p99 :       4.96 /     5.17 /     6.33 µs
  decode min/max/σ   :       4.29 /    25.08 /     0.57 µs
  throughput         : encode    259,720 ops/s | decode    205,157 ops/s
.
━━━━━━━━━━ schema-registry-avro ━━━━━━━━━━
  iterations         :     10,000
  encoded size       :      2,533 bytes   ( -23.8% vs json, 1.31x smaller)
  encode avg         :      24.39 µs      (+195.2% vs json, 2.95x slower )
  decode avg         :      13.62 µs      ( +92.3% vs json, 1.92x slower )
  encode p50/p95/p99 :      24.62 /    25.46 /    29.83 µs
  encode min/max/σ   :      21.54 /   177.50 /     2.61 µs
  decode p50/p95/p99 :      13.75 /    14.21 /    17.29 µs
  decode min/max/σ   :      11.96 /   140.42 /     2.20 µs
  throughput         : encode     40,993 ops/s | decode     73,419 ops/s
.
═══════════════ Summary (baseline = json) ═══════════════
format                      size     Δsize    enc µs     Δenc    dec µs     Δdec     enc ops/s    dec ops/s
-----------------------------------------------------------------------------------------------------------
json                       3,323    (base)      8.26   (base)      7.08   (base)       121,010      141,196
msgpack                    2,716    -18.3%      3.85   -53.4%      4.87   -31.2%       259,720      205,157
schema-registry-avro       2,533    -23.8%     24.39  +195.2%     13.62   +92.3%        40,993       73,419
```
