# Dummy LTE-Call-KPI XDR

- Source spec: `../XDR_Specification_s-probe_corr_20210729.xlsx` sheet `LTE-Call-KPI`
- `.dat` delimiter: ASCII Record Separator `0x1E`
- Record separator: newline `\n`
- Record count: 120
- Field count per record: 154
- Time format used for `timeval` fields: Unix epoch microseconds, e.g. `1778922005311671`

## Injected Scenarios

- Mostly successful LTE call KPI records
- S1AP TIMEOUT burst around records 25-64, concentrated on `MME_ID=101` and `eNB_ID=20011`
- S6a authentication failures around records 70-83, `Cause=5001`
- S11 bearer failures around records 90-99, `Cause=64`, concentrated on `SGW_ID=305`
- Normal Detach cleanup samples around records 104-109

The pipe-delimited mirror file has a header row and is easier to edit by hand.
