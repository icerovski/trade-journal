# Git Branch Setup — Safe Testing Workflow

**Goal:** isolate all the new trading-system work on its own branch so your working app
(`main`) is never at risk. You build and test on the branch, and only merge back when you're
satisfied. Until you merge, `main` is untouched — so bailing out is always safe.

> If your default branch is called `master` instead of `main`, substitute that name
> throughout. Find it with: `git branch --show-current` (while on your default branch), or
> check the branch dropdown on GitHub.

---

## 0. One-time checks

Confirm git is set up and a GitHub remote exists:

```bash
git status
git remote -v          # should list a github.com URL
```

Make sure your current work is saved before branching (branch from a clean state):

```bash
git status             # want: "nothing to commit, working tree clean"
```

If it's **not** clean, commit or park your changes first:

```bash
git add -A && git commit -m "wip: save before branching"
# or, to shelve without committing:
git stash
```

---

## 1. Start from an up-to-date main

```bash
git checkout main
git pull origin main
```

## 2. Create and switch to the test branch

```bash
git checkout -b feature/entry-stop-system
```

`-b` creates the branch **and** switches to it. The name is arbitrary; `feature/...` is just
a common convention. Verify you're on it:

```bash
git branch --show-current      # → feature/entry-stop-system
```

## 3. Push the branch to GitHub (sets its upstream)

```bash
git push -u origin feature/entry-stop-system
```

Now the branch exists on GitHub too, and future pushes are just `git push`.

## 4. Add the spec files, then run Claude Code **on this branch**

Drop `Entry_and_Stop_System.md` and `Horizon_Calibration_3to6mo.md` into the repo so Claude
Code can read them, then commit:

```bash
git add -A
git commit -m "docs: add entry/stop system + horizon calibration specs"
git push
```

Run Claude Code from this branch. Work in **small commits** — after each phase it finishes:

```bash
git add -A
git status                     # review exactly what changed
git commit -m "Phase N: <short description>"
git push
```

Small, labelled commits mean you can undo exactly one step if a phase misbehaves.

## 5. Test as you go

Run your app from the branch exactly as normal. Because every new feature is behind a config
flag defaulting to your **current** behavior (see the Claude Code instructions), the app
should behave identically until you deliberately switch a feature on.

## Working across two computers (staying synchronized)

GitHub (the `origin` remote) is the single source of truth. Both computers check out the
**same branch name** and sync through GitHub — so the whole trick is one habit:

> **Push when you finish on a machine. Pull when you start on the other.**

### First time on the second computer

If the repo isn't there yet, clone it, then get the branch:

```bash
git clone <your-repo-url>
cd <repo>
git fetch origin
git checkout feature/entry-stop-system     # makes a local copy that tracks origin
```

If the repo is already on that computer from before:

```bash
git fetch origin
git checkout feature/entry-stop-system
git pull
```

### Every time you SIT DOWN at a machine (before working)

```bash
git checkout feature/entry-stop-system     # make sure you're on the branch
git pull                                    # pull whatever the other machine pushed
git branch --show-current                   # confirm: feature/entry-stop-system
```

### Every time you STOP (before leaving the machine)

```bash
git add -A
git commit -m "..."        # commit your work — and anything Claude Code changed
git push                    # send it to GitHub so the other machine can pull it
```

If Claude Code is running on this machine, make sure its changes are committed **and pushed**
before you switch computers, or the other machine won't see them.

### "Am I in sync?"

```bash
git fetch
git status
```

`git status` will say **up to date**, **ahead** (you have unpushed commits → `git push`), or
**behind** (the remote has commits you don't → `git pull`).

### If you forgot to push and then edited the other machine

A push may be rejected as "non-fast-forward". Don't force anything — pull first (which merges
the two sides), fix anything git flags, then push:

```bash
git pull                   # merges the remote work into yours
# resolve any conflict markers git points out, then:
git add -A && git commit
git push
```

The clean way to never hit this: **always push before leaving a machine.**

---

## 6. Open a Pull Request — review everything before merging

On GitHub, the repo shows a **"Compare & pull request"** button for the pushed branch. Open a
PR from `feature/entry-stop-system` into `main`. The PR page shows the full diff of every
change in one place — a clean review checkpoint. You do **not** have to merge; a PR is also
just a nice way to see and test everything together.

## 7. When you're satisfied — merge into main

The cleanest route with two computers is to merge on GitHub, then pull `main` down on each
machine so both are current.

**On GitHub:** open the PR (Step 6) and click the green **"Merge pull request"**.

**Or locally:**

```bash
git checkout main
git pull origin main
git merge feature/entry-stop-system
git push origin main
```

**Then, on BOTH computers, update main so they match:**

```bash
git checkout main
git pull origin main
```

Once merged and verified, you can retire the branch (optional):

```bash
git branch -d feature/entry-stop-system              # local (-d = only if merged)
git push origin --delete feature/entry-stop-system   # on GitHub
```

## 8. If something goes wrong — bail out safely

```bash
# discard uncommitted changes on the branch:
git restore .

# throw away the whole experiment and return to main untouched:
git checkout main
git branch -D feature/entry-stop-system              # delete local branch
git push origin --delete feature/entry-stop-system   # delete on GitHub (optional)
```

Because `main` is never modified until step 7, abandoning the experiment can't hurt your
working app.

## Optional — keep the branch fresh if main changes meanwhile

If you commit to `main` separately while testing, pull those updates into your branch:

```bash
git checkout feature/entry-stop-system
git merge main
```

---

## Cheat sheet

| Goal | Command |
|---|---|
| Where am I? | `git branch --show-current` |
| New branch (+switch) | `git checkout -b feature/entry-stop-system` |
| Switch back to main | `git checkout main` |
| Save work | `git add -A && git commit -m "..."` |
| Send to GitHub | `git push` |
| Get others' work | `git pull` |
| Am I synced? | `git fetch && git status` |
| Set up on a 2nd computer | `git clone <url>` → `git checkout feature/entry-stop-system` |
| Undo uncommitted edits | `git restore .` |
| Shelve without committing | `git stash` (restore: `git stash pop`) |
| Delete the branch | `git branch -D feature/entry-stop-system` |

**Golden rules:** commit (or stash) before switching branches; **push before leaving a
computer and pull before starting on the other**; and never merge into `main` until the
branch behaves the way you want.
