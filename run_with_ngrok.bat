@echo off
setlocal
echo ======================================================
echo STEP 1: Lancez 'ngrok http 5000' dans un AUTRE terminal
echo STEP 2: Copiez le lien https://...
echo ======================================================
set /p NGROK_URL="Collez votre lien PUBLIC Ngrok ici : "
set PUBLIC_URL=%NGROK_URL%
echo.
echo Lancement du serveur sur le port 5000...
python app.py
pause


