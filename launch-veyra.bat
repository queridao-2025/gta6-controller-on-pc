@echo off
echo === Desconectando controles fisicos ===
powershell -Command "Get-PnpDevice -Class 'Xbox' -ErrorAction SilentlyContinue | Where-Object { $_.FriendlyName -match 'Xbox 360|Xbox One|Xbox Wireless' -and $_.Status -eq 'OK' } | ForEach-Object { Disable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false }" 2>nul

echo === Iniciando emulador de controle ===
start "" python C:\GTA6Controller\gta6-gui.py
timeout /t 3 /nobreak >nul

echo === Aguardando controle virtual ===
timeout /t 2 /nobreak >nul

echo === Iniciando Veyra ===
start "" "C:\Users\hcosc\Documents\Veyra-2.1.9-NVIDIA-win64-portable\veyra_qml_ui.exe"

echo === Pronto! ===
echo O controle virtual foi criado e o Veyra foi iniciado.
echo Desconecte controles fisicos manualmente se necessario.
pause