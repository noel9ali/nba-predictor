' run_hidden.vbs -- runs a .bat with no console window (Task Scheduler "Interactive" tasks otherwise pop a cmd window).
' Usage: wscript.exe //B //Nologo run_hidden.vbs "C:\path\to\script.bat"
' Window style 0 = hidden; True = wait for the bat, so Task Scheduler still sees the run as active and
' MultipleInstances/ExecutionTimeLimit keep working. The bat's exit code is passed through.
If WScript.Arguments.Count < 1 Then WScript.Quit 2
Set sh = CreateObject("WScript.Shell")
WScript.Quit sh.Run("cmd.exe /c """ & WScript.Arguments(0) & """", 0, True)
