Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("Wscript.Shell")
exePath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "dist\NetSplit\NetSplit.exe")
If fso.FileExists(exePath) Then
    WshShell.Run """" & exePath & """", 1, False
Else
    MsgBox "NetSplit.exe not found: " & exePath, vbCritical, "NetSplit"
End If
