# One-off generator: builds the 16 non-English language files from CORE below.
# Every language gets the core UI strings; anything missing falls back to en.json.
import json
import os

CORE = {
 "app_title": {"de":"KazaA v2. revival - Video Downloader Konverter","es":"KazaA v2. revival - Descargador y Conversor de Vídeo","ru":"KazaA v2. revival - загрузчик и конвертер видео","zh_CN":"KazaA v2. revival - 视频下载转换器","zh_TW":"KazaA v2. revival - 影片下載轉換器","ar":"KazaA v2. revival -  محمّل ومحرر الفيديو","bg":"KazaA v2. revival - видео изтегляч и конвертор","cz":"KazaA v2. revival - stahovač a konvertor videí","fi":"KazaA v2. revival - videon lataaja ja muunnin","it":"KazaA v2. revival - downloader e convertitore video","ku":"KazaA v2. revival - dakêşker û veguhezerê vîdyoyê","nl":"KazaA v2. revival - videodownloader en -converter","pl":"KazaA v2. revival - pobieranie i konwersja wideo","pt":"KazaA v2. revival - baixador e conversor de vídeo","tr":"KazaA v2. revival - video indirici ve dönüştürücü"},
 "tab_download": {"de":"Herunterladen","es":"Descargar","ru":"Загрузка","zh_CN":"下载","zh_TW":"下載","ar":"تنزيل","bg":"Изтегляне","cz":"Stahování","fi":"Lataa","it":"Scarica","ku":"Daxistin","nl":"Downloaden","pl":"Pobieranie","pt":"Baixar","tr":"İndir"},
 "tab_activity": {"de":"Aktivität","es":"Actividad","ru":"Задачи","zh_CN":"活动","zh_TW":"活動","ar":"النشاط","bg":"Активност","cz":"Aktivita","fi":"Toiminnot","it":"Attività","ku":"Çalakî","nl":"Activiteit","pl":"Aktywność","pt":"Atividade","tr":"Etkinlik"},
 "tab_convert": {"de":"Konvertieren","es":"Convertir","ru":"Конвертация","zh_CN":"转换","zh_TW":"轉換","ar":"تحويل","bg":"Конвертиране","cz":"Konverze","fi":"Muunna","it":"Converti","ku":"Veguheztin","nl":"Converteren","pl":"Konwersja","pt":"Converter","tr":"Dönüştür"},
 "start_download": {"de":"Download starten","es":"Iniciar descarga","ru":"Начать загрузку","zh_CN":"开始下载","zh_TW":"開始下載","ar":"بدء التنزيل","bg":"Започни изтегляне","cz":"Spustit stahování","fi":"Aloita lataus","it":"Avvia download","ku":"Daxistinê dest pê bike","nl":"Download starten","pl":"Rozpocznij pobieranie","pt":"Iniciar download","tr":"İndirmeyi başlat"},
 "start_convert": {"de":"Konvertierung starten","es":"Iniciar conversión","ru":"Начать конвертацию","zh_CN":"开始转换","zh_TW":"開始轉換","ar":"بدء التحويل","bg":"Започни конвертиране","cz":"Spustit konverzi","fi":"Aloita muunnos","it":"Avvia conversione","ku":"Veguheztinê dest pê bike","nl":"Conversie starten","pl":"Rozpocznij konwersję","pt":"Iniciar conversão","tr":"Dönüştürmeyi başlat"},
 "browse": {"de":"Durchsuchen...","es":"Examinar...","ru":"Обзор...","zh_CN":"浏览...","zh_TW":"瀏覽...","ar":"استعراض...","bg":"Разглеждане...","cz":"Procházet...","fi":"Selaa...","it":"Sfoglia...","ku":"Bigêre...","nl":"Bladeren...","pl":"Przeglądaj...","pt":"Procurar...","tr":"Gözat..."},
 "url_box": {"de":"Video-URL(s) hier einfügen:","es":"Pega la(s) URL del vídeo aquí:","ru":"Вставьте URL видео:","zh_CN":"在此粘贴视频链接：","zh_TW":"在此貼上影片網址：","ar":"الصق روابط الفيديو هنا:","bg":"Поставете URL адреса тук:","cz":"Vložte URL videa:","fi":"Liitä videon URL-osoite:","it":"Incolla gli URL qui:","ku":"URL-ya vîdyoyê li vir bixe:","nl":"Plak video-URL('s) hier:","pl":"Wklej adres(y) URL:","pt":"Cole o(s) URL(s) do vídeo:","tr":"Video URL'lerini yapıştırın:"},
 "download_quality": {"de":"Download-Qualität","es":"Calidad de descarga","ru":"Качество загрузки","zh_CN":"下载画质","zh_TW":"下載畫質","ar":"جودة التنزيل","bg":"Качество","cz":"Kvalita stahování","fi":"Laatu","it":"Qualità download","ku":"Kalîteya daxistinê","nl":"Downloadkwaliteit","pl":"Jakość pobierania","pt":"Qualidade","tr":"İndirme kalitesi"},
 "save_to": {"de":"Speichern in","es":"Guardar en","ru":"Сохранить в","zh_CN":"保存到","zh_TW":"儲存到","ar":"حفظ في","bg":"Запази в","cz":"Uložit do","fi":"Tallenna kohteeseen","it":"Salva in","ku":"Li vir tomar bike","nl":"Opslaan in","pl":"Zapisz do","pt":"Salvar em","tr":"Kayıt yeri"},
 "auto_convert": {"de":"Automatisch konvertieren nach","es":"Convertir automáticamente a","ru":"Автоконвертация в","zh_CN":"自动转换为","zh_TW":"自動轉換為","ar":"تحويل تلقائي إلى","bg":"Автоконвертиране към","cz":"Automaticky konvertovat do","fi":"Muunna automaattisesti","it":"Converti automaticamente in","ku":"Otomatîk veguheze","nl":"Automatisch converteren naar","pl":"Automatycznie konwertuj do","pt":"Converter automaticamente para","tr":"Otomatik dönüştür"},
 "convert_to": {"de":"Konvertieren nach","es":"Convertir a","ru":"Конвертировать в","zh_CN":"转换为","zh_TW":"轉換為","ar":"تحويل إلى","bg":"Конвертиране към","cz":"Konvertovat do","fi":"Muunna muotoon","it":"Converti in","ku":"Veguheze bo","nl":"Converteren naar","pl":"Konwertuj do","pt":"Converter para","tr":"Şuna dönüştür"},
 "cut_video": {"de":"Video schneiden","es":"Recortar vídeo","ru":"Обрезать видео","zh_CN":"剪切视频","zh_TW":"剪影片","ar":"قص الفيديو","bg":"Отрежи видео","cz":"Střih videa","fi":"Leikkaa video","it":"Taglia video","ku":"Vîdyoyê bireşîne","nl":"Video knippen","pl":"Wytnij wideo","pt":"Cortar vídeo","tr":"Videoyu kırp"},
 "volume": {"de":"Lautstärke ändern","es":"Cambiar volumen","ru":"Изменить громкость","zh_CN":"调整音量","zh_TW":"調整音量","ar":"تغيير الصوت","bg":"Сила на звука","cz":"Změnit hlasitost","fi":"Muuta äänenvoimakkuutta","it":"Cambia volume","ku":"Deng biguherîne","nl":"Volume aanpassen","pl":"Zmień głośność","pt":"Mudar volume","tr":"Sesi değiştir"},
 "menu_file": {"de":"&Datei","es":"&Archivo","ru":"&Файл","zh_CN":"文件(&F)","zh_TW":"檔案(&F)","ar":"&ملف","bg":"&Файл","cz":"&Soubor","fi":"&Tiedosto","it":"&File","ku":"&Pel","nl":"&Bestand","pl":"&Plik","pt":"&Arquivo","tr":"&Dosya"},
 "menu_help": {"de":"&Hilfe","es":"&Ayuda","ru":"&Справка","zh_CN":"帮助(&H)","zh_TW":"說明(&H)","ar":"&مساعدة","bg":"&Помощ","cz":"&Nápověda","fi":"&Ohje","it":"&Aiuto","ku":"&Alîkarî","nl":"&Help","pl":"&Pomoc","pt":"&Ajuda","tr":"&Yardım"},
 "prefs_title": {"de":"Einstellungen","es":"Preferencias","ru":"Настройки","zh_CN":"设置","zh_TW":"設定","ar":"الإعدادات","bg":"Настройки","cz":"Předvolby","fi":"Asetukset","it":"Preferenze","ku":"Vebijêrk","nl":"Voorkeuren","pl":"Ustawienia","pt":"Preferências","tr":"Tercihler"},
 "st_done": {"de":"Fertig","es":"Hecho","ru":"Готово","zh_CN":"完成","zh_TW":"完成","ar":"تم","bg":"Готово","cz":"Hotovo","fi":"Valmis","it":"Fatto","ku":"Qediya","nl":"Klaar","pl":"Gotowe","pt":"Concluído","tr":"Tamam"},
 "st_error": {"de":"Fehler","es":"Error","ru":"Ошибка","zh_CN":"错误","zh_TW":"錯誤","ar":"خطأ","bg":"Грешка","cz":"Chyba","fi":"Virhe","it":"Errore","ku":"Şaşî","nl":"Fout","pl":"Błąd","pt":"Erro","tr":"Hata"},
 "st_downloading": {"de":"Lädt herunter","es":"Descargando","ru":"Загрузка","zh_CN":"下载中","zh_TW":"下載中","ar":"جارٍ التنزيل","bg":"Изтегля се","cz":"Stahování","fi":"Ladataan","it":"Download in corso","ku":"Tê daxistin","nl":"Bezig met downloaden","pl":"Pobieranie","pt":"Baixando","tr":"İndiriliyor"},
 "best": {"de":"Beste verfügbar","es":"La mejor disponible","ru":"Наилучшее","zh_CN":"最佳可用","zh_TW":"最佳可用","ar":"أفضل متاح","bg":"Най-добро","cz":"Nejlepší dostupné","fi":"Paras saatavilla","it":"Migliore disponibile","ku":"Baştirî hey","nl":"Best beschikbaar","pl":"Najlepsza dostępna","pt":"Melhor disponível","tr":"En iyi"},
 "col_video": {"de":"Video","es":"Vídeo","ru":"Видео","zh_CN":"视频","zh_TW":"影片","ar":"الفيديو","bg":"Видео","cz":"Video","fi":"Video","it":"Video","ku":"Vîdyo","nl":"Video","pl":"Wideo","pt":"Vídeo","tr":"Video"},
 "col_progress": {"de":"Fortschritt","es":"Progreso","ru":"Прогресс","zh_CN":"进度","zh_TW":"進度","ar":"التقدم","bg":"Прогрес","cz":"Průběh","fi":"Edistyminen","it":"Avanzamento","ku":"Pêşveçûn","nl":"Voortgang","pl":"Postęp","pt":"Progresso","tr":"İlerleme"},
 "col_status": {"de":"Status","es":"Estado","ru":"Статус","zh_CN":"状态","zh_TW":"狀態","ar":"الحالة","bg":"Статус","cz":"Stav","fi":"Tila","it":"Stato","ku":"Rewş","nl":"Status","pl":"Status","pt":"Status","tr":"Durum"},
 "col_speed": {"de":"Tempo","es":"Velocidad","ru":"Скорость","zh_CN":"速度","zh_TW":"速度","ar":"السرعة","bg":"Скорост","cz":"Rychlost","fi":"Nopeus","it":"Velocità","ku":"Lez","nl":"Snelheid","pl":"Prędkość","pt":"Velocidade","tr":"Hız"},
}

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "..", "kazaa", "i18n")
    en = json.load(open(os.path.join(target, "en.json"), encoding="utf-8"))
    for code in ["de", "es", "ru", "zh_CN", "zh_TW", "ar", "bg", "cz", "fi",
                 "it", "ku", "nl", "pl", "pt", "tr"]:
        data = {k: v[code] for k, v in CORE.items() if code in v}
        with open(os.path.join(target, f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        print(code, len(data), "keys (rest falls back to en)")

if __name__ == "__main__":
    main()
