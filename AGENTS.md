# NarciBloom maintenance

- Follow the user's current task and keep each change focused. The user has authorized routine project updates to be committed and pushed directly to `main`; do not open a pull request by default.
- Complete the relevant checks before committing. Use a meaningful commit for each independently complete change and push it when ready. Do not rewrite published history or force-push.
- If two tasks need to edit this repository concurrently, coordinate ownership or use separate branches/worktrees; do not concurrently stage or commit in the same checkout. A branch/PR is appropriate when the user requests review or an isolated experiment needs it.
- Start with `python -m unittest discover -s tests -v`. Run additional game-dependent checks only for affected behavior. Say precisely what was and was not tested.
- Keep README, compatibility information and CHANGELOG aligned with the final behavior. Preserve meaningful commits and add `Co-authored-by: Codex <codex@openai.com>` to commits containing Codex contributions.
- Do not commit game archives, original or translated scenario text, executables, DLLs, saves, extracted assets, connection information or local build output. Keep dependencies pinned and preserve their notices.
- Do not equate source publication with an end-user release. Keep the developer-preview label until version recognition and install/update/uninstall have been implemented and checked.
