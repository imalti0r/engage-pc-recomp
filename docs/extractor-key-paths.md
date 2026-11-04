# Extractor key path handling

The optional title-key path caused an empty-path failure: `tools/extract_engage.py`
used to set `ENGAGE_TITLE_KEYS` to an empty string whenever `input.title_keys`
was omitted. All three `ExternalKeyReader.ReadKeyFile` calls in `P.Main` passed
that string as `titleKeysFilename`. LibHac 0.19.0 documents `null` as the value
that skips a file; an empty string is instead passed to `FileStream`.
This can fail even with a valid `prod.keys` path. The stack trace alone cannot
establish which argument was empty in a particular user's invocation.

Setup's optional title-key picker feeds `Form.title_keys`, which the pipeline
writes to `[input].title_keys` in its work config when supplied. The required
keys picker follows the same route through `Form.keys` and `[input].keys`.
`extract_engage.py --config` reads these paths and passes the common-key path
as extractor argument 1 and the optional title-key path through the environment.
Direct extractor invocations use those same argument/environment inputs; there
is no console-key input. Package tickets still provide title keys as before.

The wrapper now removes the environment variable when the optional config path
is absent, overriding any inherited value. The extractor also normalizes blank
optional paths to `null`, validates key-file paths in every mode, and returns
exit code 2 with a configuration hint on key-file failures. Key parser exception
messages are suppressed because they may contain key material.

Regression checks (synthetic files only, no game keys):

```powershell
dotnet restore tools/nx_extract/nx_extract.csproj --artifacts-path build/nx-extract-artifacts
python tests/extract_engage_test.py
python tests/nx_extract_keys_test.py
```

The native-tool tests cover all four modes for invalid paths and both package
inspection modes with absent, empty, whitespace and supplied optional paths.
An empty synthetic PFS0 package reaches the expected no-content exit code,
verifying that LibHac key loading completed. These checks do not verify a full
extraction with real game content. Rebuild the extractor and release package
to distribute the fix; existing downloaded installers retain the old code.
