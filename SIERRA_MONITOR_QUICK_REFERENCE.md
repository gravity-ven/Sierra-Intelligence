# Sierra Chart Autonomous Monitor - Quick Reference

## Common Commands

| Task | Command |
|------|----------|
| Check if running | `STATUS_SIERRA_MONITOR.bat` |
| Start manually | `START_SIERRA_MONITOR.bat` |
| Stop | `STOP_SIERRA_MONITOR.bat` |
| View logs | `notepad autonomous_monitor.log` |

## What Happens Automatically

- **On Windows Login**: Monitor starts silently
- **On Sierra Chart Launch**: Window positions detect launch
- **Every 5 Minutes**: Current positions auto-saved
- **Always**: Creates automatic backups (last 5)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Monitor not running | `START_SIERRA_MONITOR.bat` |
| Auto-start not working | `INSTALL_AUTONOMOUS_MONITOR.bat` (Admin) |
| Check for errors | `notepad autonomous_monitor.log` |

## Log Quick Check

```batch
powershell Get-Content autonomous_monitor.log -Tail 20
```

- `[SUCCESS]` - Operation completed
- `[INFO]` - Normal operation
- `[WARNING]` - Minor issue
- `[ERROR]` - Needs attention

## Emergency Reset

```batch
STOP_SIERRA_MONITOR.bat
del autonomous_monitor.pid
del sierra_chart_window_state.json
START_SIERRA_MONITOR.bat
```

**Version**: 2.0.0 (Fully Autonomous)
