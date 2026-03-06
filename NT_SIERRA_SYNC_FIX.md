# Fix NT/Sierra Startup and Sync

## Immediate Fix Options

### Option 1: Batch file
```
NT_Sierra_Chart_Sync.bat
```

### Option 2: PowerShell
```powershell
NT_Sierra_Chart_Sync.ps1
```

### Option 3: Manual
1. Start Sierra Chart
2. Start NinjaTrader
3. Wait for NT login
4. Run chart sync from project directory

## Verification

```powershell
Get-Process SierraChart_64, NinjaTrader | Select Name, Id, MainWindowTitle
```

## Expected Behavior

1. Sierra Chart opens with configured charts
2. NinjaTrader opens, auto-logs in
3. NT Monitor positions all NT windows
4. Chart Sync opens matching instruments: MES, MNQ, MCL, MGC, MYM, M2K, MBT

## MASTER_STARTUP.ps1 Phases

- Phase 2.5: Sierra Chart with retry logic (3 attempts)
- Phase 2.6: NinjaTrader with retry logic (3 attempts)
- Phase 5.5: NT watchdogs (Monitor + AutoLogin)
- Phase 5.6: Chart sync (60s delay for login)
