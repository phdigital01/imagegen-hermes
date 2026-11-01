# Security

## Reporting a problem

Report a vulnerability through
[GitHub private vulnerability reporting](https://github.com/phdigital01/imagegen-hermes/security/advisories/new).
Do not open a public issue for it. Include the ImageGen and Hermes versions and the steps to
reproduce the problem.

Only the latest release gets fixes.

## What ImageGen handles

- It reads provider keys only through the Hermes secret store and never sends them to the screen.
- It sends prompts and reference images to the provider you pick. See "What this plugin does on your
  machine" in the [README](README.md).
- It stores images, history and the spending ledger in `$HERMES_HOME/plugin-data/imagegen/`.

Never paste a key in an issue, a log or a screenshot.
