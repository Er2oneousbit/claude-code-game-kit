// ---------------------------------------------------------------------------
// cli.rs
// Purpose : The program's own command line: --debug, --smoke N, --screenshot, --record, --version, --help,
//           and everything after `--` handed to the game untouched (game::configure reads it).
// Usage   : project_crimson_nebula [--debug] [--smoke N] [--screenshot FILE.png] [--record DIR] [--record-every N] [--record-from N]
//           [-- game options]
// Notes   : Standard library only, unit tested below. Strict on purpose: a typo is an error (exit 2), not a
//           silently ignored flag, so a smoke run never "passes" with the wrong settings.
// Authored: Written with Claude (Opus 5.5, claude-opus-5-5)
// ---------------------------------------------------------------------------
use std::path::PathBuf;

/// Upper bound for --smoke and --record-every, so a typo cannot ask for a run that never ends.
pub const COUNT_MAX: u32 = 100_000;

#[derive(Debug, Clone, PartialEq)]
pub struct Cli {
    pub debug: bool,
    pub version: bool,
    pub help: bool,
    /// Run this many frames, then exit. Headless unless a capture option asks for a window.
    pub smoke: Option<u32>,
    pub screenshot: Option<PathBuf>,
    pub record: Option<PathBuf>,
    pub record_every: u32,
    /// First frame --record saves (skip a race's first minute to film its third lap).
    pub record_from: u32,
    /// Everything after `--`, for game::configure.
    pub game_args: Vec<String>,
}

impl Default for Cli {
    fn default() -> Self {
        Self {
            debug: false,
            version: false,
            help: false,
            smoke: None,
            screenshot: None,
            record: None,
            record_every: 4,
            record_from: 1,
            game_args: Vec::new(),
        }
    }
}

impl Cli {
    /// Screenshots need the renderer, so a capture run opens a window even with --smoke.
    pub fn wants_window(&self) -> bool {
        self.smoke.is_none() || self.screenshot.is_some() || self.record.is_some()
    }
}

pub const HELP: &str = "\
Options:
  --debug              verbose logging for this game's own log lines
  --smoke N            run N frames (one 1/60 s tick each), print BOOT_OK and SMOKE_DONE, exit
  --screenshot FILE    with --smoke: open a window and save the last frame (PNG)
  --record DIR         with --smoke: open a window and save every Nth frame as PNG
  --record-every N     frame spacing for --record (default 4)
  --record-from N      first frame --record saves (default 1)
  --version            print the name and version
  -h, --help           this text
  -- ...               everything after it goes to the game (game options below)
";

/// Parses the arguments after the program name.
pub fn parse<I: IntoIterator<Item = String>>(args: I) -> Result<Cli, String> {
    let mut cli = Cli::default();
    let mut it = args.into_iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--debug" => cli.debug = true,
            "--version" => cli.version = true,
            "-h" | "--help" => cli.help = true,
            "--smoke" => cli.smoke = Some(count(&mut it, "--smoke")?),
            "--screenshot" => cli.screenshot = Some(path(&mut it, "--screenshot")?),
            "--record" => cli.record = Some(path(&mut it, "--record")?),
            "--record-every" => cli.record_every = count(&mut it, "--record-every")?,
            "--record-from" => cli.record_from = count(&mut it, "--record-from")?,
            "--" => {
                cli.game_args = it.by_ref().collect();
                break;
            }
            other => return Err(format!("unknown option {other:?} (game options go after `--`)")),
        }
    }
    if cli.smoke.is_none() && (cli.screenshot.is_some() || cli.record.is_some()) {
        return Err("--screenshot and --record need --smoke N (how many frames to run)".into());
    }
    Ok(cli)
}

fn count(it: &mut impl Iterator<Item = String>, name: &str) -> Result<u32, String> {
    let value = it.next().ok_or(format!("{name} needs a number"))?;
    match value.parse::<u32>() {
        Ok(n) if (1..=COUNT_MAX).contains(&n) => Ok(n),
        _ => Err(format!(
            "{name} needs a whole number from 1 to {COUNT_MAX}, got {value:?}"
        )),
    }
}

fn path(it: &mut impl Iterator<Item = String>, name: &str) -> Result<PathBuf, String> {
    it.next().map(PathBuf::from).ok_or(format!("{name} needs a path"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn no_arguments_means_a_normal_windowed_run() {
        let cli = parse(args(&[])).unwrap();
        assert_eq!(cli, Cli::default());
        assert!(cli.wants_window());
    }

    #[test]
    fn smoke_alone_is_headless_and_capture_opens_a_window() {
        assert!(!parse(args(&["--smoke", "120"])).unwrap().wants_window());
        assert!(
            parse(args(&["--smoke", "5", "--screenshot", "a.png"]))
                .unwrap()
                .wants_window()
        );
    }

    #[test]
    fn everything_after_the_separator_goes_to_the_game() {
        let cli = parse(args(&["--smoke", "9", "--", "--autoplay", "right", "--debug"])).unwrap();
        assert_eq!(cli.smoke, Some(9));
        assert!(!cli.debug, "--debug after `--` belongs to the game");
        assert_eq!(cli.game_args, args(&["--autoplay", "right", "--debug"]));
    }

    #[test]
    fn bad_counts_and_unknown_options_are_errors() {
        assert!(parse(args(&["--smoke", "0"])).is_err());
        assert!(parse(args(&["--smoke", "100001"])).is_err());
        assert!(parse(args(&["--smoke", "ten"])).is_err());
        assert!(parse(args(&["--smoke"])).is_err());
        assert!(parse(args(&["--smok", "5"])).is_err());
        assert!(
            parse(args(&["--screenshot", "a.png"])).is_err(),
            "capture needs a frame count"
        );
        assert!(parse(args(&["--smoke", "5", "--record-from", "0"])).is_err());
        let late_start = parse(args(&["--smoke", "9", "--record-from", "7"])).unwrap();
        assert_eq!(late_start.record_from, 7);
    }
}
