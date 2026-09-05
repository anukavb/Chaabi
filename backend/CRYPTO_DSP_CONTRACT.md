# DSP-to-Crypto Feature Contract

The DSP returns a variable-length `formant_frames` list. Six frames contain 18
raw frequency measurements, but they do not guarantee 18 distinct 25 Hz bins.

The crypto module must therefore:

1. flatten F1, F2, and F3 from every valid DSP frame;
2. quantize the frequencies into 25 Hz bins;
3. remove duplicate bins;
4. verify that the distinct count is at least `coefficient_count`;
5. select the required genuine bins deterministically.

Use the adapter:

```python
from crypto_vault import formant_values_from_dsp

formants = formant_values_from_dsp(dsp_result)
vault = generate_vault(formants)
```

For the default 10-byte `CHABI-DEMO` secret and eight Reed-Solomon parity bytes,
`coefficient_count` is 18. The value is stored in the vault and must not be
hardcoded during authentication.

If there are fewer than 18 distinct bins, request a longer or more phonetically
varied recording. Do not duplicate measurements to reach the required count.
