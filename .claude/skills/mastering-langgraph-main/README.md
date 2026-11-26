# mastering-langgraph skill for Kiro

A Kiro agent skill that gives your coding assistant validated LangGraph patterns: state and reducers, nodes, conditional edges and loops, checkpointers and `thread_id`, and human-in-the-loop with `interrupt()`. It also carries the mistakes assistants repeat when working from memory instead of current docs.

## Install

1. Download this repo. Click **Code → Download ZIP**, then unzip it. (Or `git clone` it.)
2. Open your Kiro skills folder: `~/.kiro/skills`

   On macOS, press `Cmd+Shift+G` in Finder and type `~/.kiro/skills`. Create the `skills` folder if it is not there yet. Hidden folders show with `Cmd+Shift+.`

   On Windows that path is `%USERPROFILE%\.kiro\skills`, and on Linux it is `~/.kiro/skills`.
3. Drag the skill folder into it.
4. Start a new Kiro chat session so it picks up the new skill.

You should end up with this:

```text
~/.kiro/skills/
└── mastering-langgraph/
    └── SKILL.md
```

Installing under `~/.kiro` makes the skill available in every project. To scope it to one project instead, drop the same folder into that project's `.kiro/skills/`.

## Use it

Name the skill at the start of your prompt:

```text
Using the mastering-langgraph skill, add a conditional edge that loops the agent
back to its tool node until it stops requesting tools.
```

Kiro also loads it on its own when a prompt is about LangGraph. Naming it removes the guesswork.

## Troubleshooting

**Kiro does not seem to use it.** Check the nesting. A GitHub ZIP unzips to a folder named after the repo with `-main` on the end, so you can end up with `~/.kiro/skills/mastering-langgraph-agent-skill-main/mastering-langgraph/SKILL.md`. `SKILL.md` needs to sit one level deep, directly inside a folder in `skills/`.

**No `.kiro` folder in your home directory.** Create it: `mkdir -p ~/.kiro/skills`
