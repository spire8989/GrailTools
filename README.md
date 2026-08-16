# GrailTools

Local development tools for authoring and validating the sibling [Grail](../Grail) game project.

## Content Editor

The current tool is the dependency-free Python/browser Content Editor:

```powershell
cd ContentEditor
python server.py
```

Open <http://127.0.0.1:5173/>. The editor reads the canonical definitions from
the sibling `Grail` repository and writes only explicitly saved, validated
changes back to that project. See [ContentEditor/README.md](ContentEditor/README.md)
for supported content, setup, save behavior, and tests.

This repository contains development tooling only; it is intentionally kept
separate from the Grail game submission.
