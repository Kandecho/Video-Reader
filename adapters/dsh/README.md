# Video Reader + Scroll Agent · DSH adapter 0.1.0

Connect the complete [Video Reader](https://github.com/Kandecho/Video-Reader) installation to DSH: video reading, shared queues/history and Scroll's personal Bilibili workflows. This small bundle starts the two existing MCP servers; the queue remains the independent `reading_tasks` module, exposed through Reader's `video_tasks`. It does not copy the core, models, credentials or cached media.

## Install on Windows

First [install the core](https://github.com/Kandecho/Video-Reader/blob/main/docs/getting-started.md) and pass `run.ps1 doctor`. Tested with core 0.10.0rc6 and DSH 0.2.2-rc.1. Set the existing installation directory in the same PowerShell session used to launch DSH:

```powershell
$env:VIDEO_READER_ROOT = 'D:/tools/Video Reader'
dsh plugin --profile web add 'https://github.com/Kandecho/Video-Reader/releases/download/dsh-video-reader%400.1.0/dsh-video-reader-0.1.0.tgz'
dsh web
```

Restart an already running DSH process from this session. Refreshing a page does not update the process environment. Installing the bundle alone does not install Python, FFmpeg, models or Bilibili credentials. You may point `VIDEO_READER_CONFIG` at a different existing absolute config path; both servers use the same selection.

For local development, run `npm pack` in this directory and pass the resulting absolute tgz path to `dsh plugin --profile <name> add`. The package has no install scripts or bundled binaries. Build the tgz again before testing changes.

## Use it

Ask DSH to read a video and provide timestamped points, then ask about a frame. `mcp__video_reader__*` handles video materials and shared tasks; `mcp__scroll_agent__*` handles personal account workflows. The model must support image input to inspect native frames. Headless model login and troubleshooting are covered in the [DSH guide](https://github.com/Kandecho/Video-Reader/blob/main/docs/dsh.md).

Scroll can use a separately logged-in Bilibili account, its own homepage recommendations and authorized private messages with your main account. This has been used with real accounts; it is not a placeholder. [Capability status](https://github.com/Kandecho/Video-Reader/blob/main/docs/capabilities.md) distinguishes working features, ongoing trials and unfinished automation. Installing this adapter does not enable a schedule or authorize messaging. Receiving a link, queuing it, preparing material and actually finishing a reading are different states.

The complete source download and this thin adapter are in the same [release](https://github.com/Kandecho/Video-Reader/releases/tag/dsh-video-reader%400.1.0). Core and adapter versions are separate. No npm publication or plugin-index listing is implied.

## Remove

```powershell
dsh plugin --profile web remove dsh-video-reader
```

Restart DSH. Removing this adapter leaves the shared core and its local records intact. MIT; the installed core's third-party notices and model licenses still apply.
