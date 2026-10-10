Option Explicit

Dim fileSystem, shell, projectRoot, electronPath
Set fileSystem = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
electronPath = fileSystem.BuildPath(projectRoot, "node_modules\electron\dist\electron.exe")

If Not fileSystem.FileExists(electronPath) Then
  MsgBox "Primero ejecuta npm install en la carpeta del proyecto.", vbExclamation, "iPhone Wi-Fi Transfer"
  WScript.Quit 1
End If

shell.Run Chr(34) & electronPath & Chr(34) & " " & Chr(34) & projectRoot & Chr(34), 0, False
