# Parser tests

Run public checks with `python -m unittest discover tests` from this repository.

`private_fixtures/` and `private_expected/` are git-ignored. To add a local
regression case, put PDFs in `private_fixtures/`, preview the proposed stable
field values with `python tests/create_private_goldens.py`, and review them
before writing the local JSON files with `python tests/create_private_goldens.py --write`.

Each JSON file has this form:

```json
{
  "SourceFile": "client-file.pdf",
  "Expected": {
    "ReturnType": "GSTR1",
    "Status": "OK"
  }
}
```

Only assert stable, review-relevant fields. Never add client PDFs or extracted
data to Git.
