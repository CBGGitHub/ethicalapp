"""Translations for the setup wizard (used by build.py).

Inno Setup translates its own buttons and pages (Languages\\*.isl); the texts below are ours: install types,
app descriptions, tasks and the welcome page. The language picked in setup also becomes the apps' language
(written to the same setting the launcher's 🌐 menu uses), unless one was already chosen.
Add a language: an entry in LANGS, a text in every MSG entry and in WELCOME (English is the fallback).
"""

# app language code -> Inno messages file (compiler: = Inno's own folder; others live in installer/languages)
LANGS = [
    ("en", "compiler:Default.isl"),
    ("es", "compiler:Languages\\Spanish.isl"),
    ("pt_BR", "compiler:Languages\\BrazilianPortuguese.isl"),
    ("fr", "compiler:Languages\\French.isl"),
    ("de", "compiler:Languages\\German.isl"),
    ("it", "compiler:Languages\\Italian.isl"),
    ("nl", "compiler:Languages\\Dutch.isl"),
    ("pl", "compiler:Languages\\Polish.isl"),
    ("tr", "compiler:Languages\\Turkish.isl"),
    ("ru", "compiler:Languages\\Russian.isl"),
    ("id", "languages\\Indonesian.isl"),
    ("ja", "compiler:Languages\\Japanese.isl"),
    ("ko", "compiler:Languages\\Korean.isl"),
    ("zh_CN", "languages\\ChineseSimplified.isl"),
]


def inno_name(code):
    return code.replace("_", "")


MSG = {
    "TypeFull": {
        "en": "Everything (recommended)", "es": "Todo (recomendado)", "pt_BR": "Tudo (recomendado)",
        "fr": "Tout (recommandé)", "de": "Alles (empfohlen)", "it": "Tutto (consigliato)", "nl": "Alles (aanbevolen)",
        "pl": "Wszystko (zalecane)", "tr": "Hepsi (önerilen)", "ru": "Всё (рекомендуется)", "id": "Semua (disarankan)",
        "ja": "すべて（推奨）", "ko": "모두(권장)", "zh_CN": "全部（推荐）"},
    "TypeOffice": {
        "en": "Office apps only (PDF, Document, Spreadsheet, Presentation)",
        "es": "Solo aplicaciones de oficina (PDF, documentos, hojas de cálculo, presentaciones)",
        "pt_BR": "Só aplicativos de escritório (PDF, documentos, planilhas, apresentações)",
        "fr": "Applications bureautiques seulement (PDF, documents, tableur, présentations)",
        "de": "Nur Büro-Apps (PDF, Dokumente, Tabellen, Präsentationen)",
        "it": "Solo app per l'ufficio (PDF, documenti, fogli di calcolo, presentazioni)",
        "nl": "Alleen kantoorapps (PDF, documenten, spreadsheets, presentaties)",
        "pl": "Tylko aplikacje biurowe (PDF, dokumenty, arkusze, prezentacje)",
        "tr": "Yalnızca ofis uygulamaları (PDF, belge, elektronik tablo, sunu)",
        "ru": "Только офисные приложения (PDF, документы, таблицы, презентации)",
        "id": "Hanya aplikasi kantor (PDF, dokumen, lembar kerja, presentasi)",
        "ja": "オフィス アプリのみ（PDF、文書、表計算、プレゼンテーション）",
        "ko": "사무용 앱만(PDF, 문서, 스프레드시트, 프레젠테이션)",
        "zh_CN": "仅办公应用（PDF、文档、电子表格、演示文稿）"},
    "TypeCustom": {
        "en": "Let me choose", "es": "Elegir yo", "pt_BR": "Quero escolher", "fr": "Je choisis",
        "de": "Selbst auswählen", "it": "Scelgo io", "nl": "Zelf kiezen", "pl": "Wybiorę sam", "tr": "Ben seçeyim",
        "ru": "Выбрать самому", "id": "Saya pilih sendiri", "ja": "自分で選ぶ", "ko": "직접 선택", "zh_CN": "自己选择"},
    "Core": {
        "en": "EthicalApp core (shared files, user guide)", "es": "Núcleo de EthicalApp (archivos comunes, guía)",
        "pt_BR": "Base do EthicalApp (arquivos comuns, guia)", "fr": "Base d'EthicalApp (fichiers communs, guide)",
        "de": "EthicalApp-Grundlage (gemeinsame Dateien, Anleitung)", "it": "Base di EthicalApp (file comuni, guida)",
        "nl": "EthicalApp-basis (gedeelde bestanden, handleiding)", "pl": "Podstawa EthicalApp (wspólne pliki, przewodnik)",
        "tr": "EthicalApp çekirdeği (ortak dosyalar, kılavuz)", "ru": "Основа EthicalApp (общие файлы, руководство)",
        "id": "Inti EthicalApp (file bersama, panduan)", "ja": "EthicalApp の基本（共通ファイル、ガイド）",
        "ko": "EthicalApp 기본(공용 파일, 가이드)", "zh_CN": "EthicalApp 核心（共享文件、使用指南）"},
    "Desc_pdf": {
        "en": "View, edit text, annotate, fill forms, sign, merge and split PDFs",
        "es": "Ver, editar texto, anotar, rellenar formularios, firmar, unir y dividir PDF",
        "pt_BR": "Ver, editar texto, anotar, preencher formulários, assinar, juntar e dividir PDFs",
        "fr": "Afficher, modifier le texte, annoter, remplir, signer, fusionner et diviser des PDF",
        "de": "PDFs ansehen, Text bearbeiten, kommentieren, ausfüllen, signieren, zusammenfügen, aufteilen",
        "it": "Visualizza, modifica il testo, annota, compila, firma, unisci e dividi PDF",
        "nl": "PDF's bekijken, tekst bewerken, aantekeningen, invullen, ondertekenen, samenvoegen, splitsen",
        "pl": "Przeglądaj, edytuj tekst, dodawaj adnotacje, wypełniaj, podpisuj, scalaj i dziel PDF-y",
        "tr": "PDF görüntüleyin, metni düzenleyin, not ekleyin, form doldurun, imzalayın, birleştirin, bölün",
        "ru": "Просмотр, правка текста, пометки, формы, подпись, объединение и разделение PDF",
        "id": "Lihat, edit teks, beri anotasi, isi formulir, tanda tangani, gabung dan pisahkan PDF",
        "ja": "PDF の表示、テキスト編集、注釈、フォーム入力、署名、結合、分割",
        "ko": "PDF 보기, 텍스트 편집, 주석, 양식 작성, 서명, 병합 및 분할",
        "zh_CN": "查看 PDF、编辑文字、批注、填写表单、签名、合并和拆分"},
    "Desc_document": {
        "en": "Write documents - opens and saves Word (.docx) files",
        "es": "Escribir documentos: abre y guarda archivos de Word (.docx)",
        "pt_BR": "Escrever documentos: abre e salva arquivos do Word (.docx)",
        "fr": "Rédiger des documents : ouvre et enregistre les fichiers Word (.docx)",
        "de": "Dokumente schreiben – öffnet und speichert Word-Dateien (.docx)",
        "it": "Scrivi documenti: apre e salva file Word (.docx)",
        "nl": "Documenten schrijven - opent en bewaart Word-bestanden (.docx)",
        "pl": "Pisz dokumenty – otwiera i zapisuje pliki Worda (.docx)",
        "tr": "Belge yazın - Word (.docx) dosyalarını açar ve kaydeder",
        "ru": "Документы — открывает и сохраняет файлы Word (.docx)",
        "id": "Tulis dokumen - membuka dan menyimpan file Word (.docx)",
        "ja": "文書の作成 — Word（.docx）ファイルを開いて保存",
        "ko": "문서 작성 — Word(.docx) 파일 열기 및 저장",
        "zh_CN": "撰写文档 — 打开和保存 Word（.docx）文件"},
    "Desc_spreadsheet": {
        "en": "Spreadsheets with formulas and charts - Excel (.xlsx) files",
        "es": "Hojas de cálculo con fórmulas y gráficos: archivos de Excel (.xlsx)",
        "pt_BR": "Planilhas com fórmulas e gráficos: arquivos do Excel (.xlsx)",
        "fr": "Tableurs avec formules et graphiques : fichiers Excel (.xlsx)",
        "de": "Tabellen mit Formeln und Diagrammen – Excel-Dateien (.xlsx)",
        "it": "Fogli di calcolo con formule e grafici: file Excel (.xlsx)",
        "nl": "Spreadsheets met formules en grafieken - Excel-bestanden (.xlsx)",
        "pl": "Arkusze z formułami i wykresami – pliki Excela (.xlsx)",
        "tr": "Formül ve grafikli elektronik tablolar - Excel (.xlsx) dosyaları",
        "ru": "Таблицы с формулами и диаграммами — файлы Excel (.xlsx)",
        "id": "Lembar kerja dengan rumus dan bagan - file Excel (.xlsx)",
        "ja": "数式とグラフの表計算 — Excel（.xlsx）ファイル",
        "ko": "수식과 차트가 있는 스프레드시트 — Excel(.xlsx) 파일",
        "zh_CN": "带公式和图表的电子表格 — Excel（.xlsx）文件"},
    "Desc_presentation": {
        "en": "Slide decks and slideshows - PowerPoint (.pptx) files",
        "es": "Presentaciones y diapositivas: archivos de PowerPoint (.pptx)",
        "pt_BR": "Apresentações e slides: arquivos do PowerPoint (.pptx)",
        "fr": "Présentations et diaporamas : fichiers PowerPoint (.pptx)",
        "de": "Präsentationen und Bildschirmpräsentationen – PowerPoint-Dateien (.pptx)",
        "it": "Presentazioni e diapositive: file PowerPoint (.pptx)",
        "nl": "Presentaties en diavoorstellingen - PowerPoint-bestanden (.pptx)",
        "pl": "Prezentacje i pokazy slajdów – pliki PowerPointa (.pptx)",
        "tr": "Sunular ve slayt gösterileri - PowerPoint (.pptx) dosyaları",
        "ru": "Презентации и слайд-шоу — файлы PowerPoint (.pptx)",
        "id": "Presentasi dan tayangan slide - file PowerPoint (.pptx)",
        "ja": "スライドとスライド ショー — PowerPoint（.pptx）ファイル",
        "ko": "슬라이드와 슬라이드 쇼 — PowerPoint(.pptx) 파일",
        "zh_CN": "演示文稿和幻灯片放映 — PowerPoint（.pptx）文件"},
    "Desc_photo": {
        "en": "Layered photo editor - Photoshop (.psd), PNG, JPG and more",
        "es": "Editor de fotos con capas: Photoshop (.psd), PNG, JPG y más",
        "pt_BR": "Editor de fotos com camadas: Photoshop (.psd), PNG, JPG e mais",
        "fr": "Éditeur photo à calques : Photoshop (.psd), PNG, JPG et plus",
        "de": "Fotobearbeitung mit Ebenen – Photoshop (.psd), PNG, JPG und mehr",
        "it": "Editor di foto a livelli: Photoshop (.psd), PNG, JPG e altro",
        "nl": "Fotobewerker met lagen - Photoshop (.psd), PNG, JPG en meer",
        "pl": "Edytor zdjęć z warstwami – Photoshop (.psd), PNG, JPG i inne",
        "tr": "Katmanlı fotoğraf düzenleyici - Photoshop (.psd), PNG, JPG ve daha fazlası",
        "ru": "Фоторедактор со слоями — Photoshop (.psd), PNG, JPG и другие",
        "id": "Editor foto berlapis - Photoshop (.psd), PNG, JPG, dan lainnya",
        "ja": "レイヤー対応の写真編集 — Photoshop（.psd）、PNG、JPG など",
        "ko": "레이어 사진 편집기 — Photoshop(.psd), PNG, JPG 등",
        "zh_CN": "支持图层的照片编辑器 — Photoshop（.psd）、PNG、JPG 等"},
    "Desc_converter": {
        "en": "Convert and compress audio, video, pictures and documents; zip/unzip",
        "es": "Convierte y comprime audio, vídeo, imágenes y documentos; comprimir/extraer zip",
        "pt_BR": "Converte e comprime áudio, vídeo, imagens e documentos; compactar/extrair zip",
        "fr": "Convertir et compresser audio, vidéo, images et documents ; zip/décompresser",
        "de": "Audio, Video, Bilder und Dokumente umwandeln und komprimieren; zippen/entpacken",
        "it": "Converti e comprimi audio, video, immagini e documenti; zip/estrai",
        "nl": "Audio, video, afbeeldingen en documenten converteren en comprimeren; zippen/uitpakken",
        "pl": "Konwertuj i kompresuj dźwięk, wideo, obrazy i dokumenty; pakuj/rozpakowuj",
        "tr": "Ses, video, resim ve belgeleri dönüştürün ve sıkıştırın; zip/ayıkla",
        "ru": "Преобразование и сжатие аудио, видео, изображений и документов; zip/распаковка",
        "id": "Konversi dan kompres audio, video, gambar, dan dokumen; zip/ekstrak",
        "ja": "音声・動画・画像・文書の変換と圧縮、ZIP 圧縮・展開",
        "ko": "오디오, 동영상, 이미지, 문서 변환 및 압축, zip 압축/풀기",
        "zh_CN": "转换和压缩音频、视频、图片和文档；压缩/解压 zip"},
    "Desc_database": {
        "en": "Databases: tables, forms, queries, relationships and reports",
        "es": "Bases de datos: tablas, formularios, consultas, relaciones e informes",
        "pt_BR": "Bancos de dados: tabelas, formulários, consultas, relações e relatórios",
        "fr": "Bases de données : tables, formulaires, requêtes, relations et états",
        "de": "Datenbanken: Tabellen, Formulare, Abfragen, Beziehungen und Berichte",
        "it": "Database: tabelle, maschere, query, relazioni e report",
        "nl": "Databases: tabellen, formulieren, query's, relaties en rapporten",
        "pl": "Bazy danych: tabele, formularze, kwerendy, relacje i raporty",
        "tr": "Veritabanları: tablolar, formlar, sorgular, ilişkiler ve raporlar",
        "ru": "Базы данных: таблицы, формы, запросы, связи и отчёты",
        "id": "Basis data: tabel, formulir, kueri, relasi, dan laporan",
        "ja": "データベース: テーブル、フォーム、クエリ、リレーションシップ、レポート",
        "ko": "데이터베이스: 테이블, 폼, 쿼리, 관계, 보고서",
        "zh_CN": "数据库：表、窗体、查询、关系和报表"},
    "Desc_stickynotes": {
        "en": "Notes and to-do lists that stay on your desktop",
        "es": "Notas y listas de tareas que se quedan en tu escritorio",
        "pt_BR": "Notas e listas de tarefas que ficam na sua área de trabalho",
        "fr": "Notes et listes de tâches qui restent sur votre bureau",
        "de": "Notizen und To-do-Listen, die auf dem Desktop bleiben",
        "it": "Note ed elenchi di cose da fare che restano sul desktop",
        "nl": "Notities en takenlijsten die op je bureaublad blijven",
        "pl": "Notatki i listy zadań, które zostają na pulpicie",
        "tr": "Masaüstünüzde kalan notlar ve yapılacaklar listeleri",
        "ru": "Заметки и списки дел, которые остаются на рабочем столе",
        "id": "Catatan dan daftar tugas yang tetap di desktop Anda",
        "ja": "デスクトップに貼っておけるメモと ToDo リスト",
        "ko": "바탕 화면에 머무는 메모와 할 일 목록",
        "zh_CN": "留在桌面上的便笺和待办清单"},
    "Desc_snip": {
        "en": "Screenshots of your screen that you can mark up (keyboard shortcut of your choice)",
        "es": "Capturas de pantalla que puedes marcar (con el atajo de teclado que elijas)",
        "pt_BR": "Capturas de tela que você pode marcar (com o atalho de teclado que escolher)",
        "fr": "Captures d'écran à annoter (avec le raccourci clavier de votre choix)",
        "de": "Bildschirmfotos zum Markieren (mit einem Tastenkürzel deiner Wahl)",
        "it": "Screenshot da annotare (con la scorciatoia da tastiera che preferisci)",
        "nl": "Schermafbeeldingen om op te tekenen (met een sneltoets naar keuze)",
        "pl": "Zrzuty ekranu do opisania (ze skrótem klawiszowym do wyboru)",
        "tr": "İşaretleyebileceğiniz ekran görüntüleri (seçtiğiniz bir kısayol tuşuyla)",
        "ru": "Снимки экрана с пометками (сочетание клавиш на ваш выбор)",
        "id": "Tangkapan layar yang bisa diberi tanda (dengan pintasan keyboard pilihan Anda)",
        "ja": "書き込みできるスクリーンショット（ショートカット キーは自由に設定）",
        "ko": "표시할 수 있는 스크린샷(원하는 바로 가기 키 사용)",
        "zh_CN": "可以标注的截图（快捷键可自选）"},
    "Desc_planner": {
        "en": "Reminders (like daily supplements) and a calendar that pop up on time",
        "es": "Recordatorios (como suplementos diarios) y un calendario que avisan a tiempo",
        "pt_BR": "Lembretes (como suplementos diários) e um calendário que avisam na hora",
        "fr": "Rappels (comme les compléments du jour) et un calendrier qui préviennent à l'heure",
        "de": "Erinnerungen (z. B. tägliche Nahrungsergänzung) und ein Kalender, die pünktlich erscheinen",
        "it": "Promemoria (come gli integratori quotidiani) e un calendario che avvisano in tempo",
        "nl": "Herinneringen (zoals dagelijkse supplementen) en een agenda die op tijd verschijnen",
        "pl": "Przypomnienia (np. o codziennych suplementach) i kalendarz, które ostrzegają na czas",
        "tr": "Zamanında beliren anımsatıcılar (günlük takviyeler gibi) ve takvim",
        "ru": "Напоминания (например, о ежедневных добавках) и календарь, которые срабатывают вовремя",
        "id": "Pengingat (seperti suplemen harian) dan kalender yang muncul tepat waktu",
        "ja": "時間どおりに知らせるリマインダー（毎日のサプリなど）とカレンダー",
        "ko": "제때 알려 주는 미리 알림(매일 영양제 등)과 달력",
        "zh_CN": "准时弹出的提醒事项（如每天吃保健品）和日历"},
    "GroupShortcuts": {
        "en": "Shortcuts:", "es": "Accesos directos:", "pt_BR": "Atalhos:", "fr": "Raccourcis :", "de": "Verknüpfungen:",
        "it": "Collegamenti:", "nl": "Snelkoppelingen:", "pl": "Skróty:", "tr": "Kısayollar:", "ru": "Ярлыки:",
        "id": "Pintasan:", "ja": "ショートカット:", "ko": "바로 가기:", "zh_CN": "快捷方式："},
    "GroupWindows": {
        "en": "Windows integration:", "es": "Integración con Windows:", "pt_BR": "Integração com o Windows:",
        "fr": "Intégration à Windows :", "de": "Windows-Integration:", "it": "Integrazione con Windows:",
        "nl": "Windows-integratie:", "pl": "Integracja z Windows:", "tr": "Windows tümleştirmesi:",
        "ru": "Интеграция с Windows:", "id": "Integrasi Windows:", "ja": "Windows との連携:", "ko": "Windows 통합:",
        "zh_CN": "Windows 集成："},
    "GroupAI": {
        "en": "AI:", "es": "IA:", "pt_BR": "IA:", "fr": "IA :", "de": "KI:", "it": "IA:", "nl": "AI:", "pl": "AI:",
        "tr": "Yapay zekâ:", "ru": "ИИ:", "id": "AI:", "ja": "AI:", "ko": "AI:", "zh_CN": "AI："},
    "TaskDesktop": {
        "en": "Create desktop shortcuts for the chosen apps",
        "es": "Crear accesos directos en el escritorio para las aplicaciones elegidas",
        "pt_BR": "Criar atalhos na área de trabalho para os aplicativos escolhidos",
        "fr": "Créer des raccourcis sur le bureau pour les applications choisies",
        "de": "Desktop-Verknüpfungen für die gewählten Apps anlegen",
        "it": "Crea collegamenti sul desktop per le app scelte",
        "nl": "Snelkoppelingen op het bureaublad maken voor de gekozen apps",
        "pl": "Utwórz skróty na pulpicie dla wybranych aplikacji",
        "tr": "Seçilen uygulamalar için masaüstü kısayolları oluştur",
        "ru": "Создать ярлыки на рабочем столе для выбранных приложений",
        "id": "Buat pintasan desktop untuk aplikasi yang dipilih",
        "ja": "選んだアプリのデスクトップ ショートカットを作成",
        "ko": "선택한 앱의 바탕 화면 바로 가기 만들기",
        "zh_CN": "为所选应用创建桌面快捷方式"},
    "TaskPin": {
        "en": "Help me pin EthicalApp to the taskbar / Start (shows you how after setup - Windows only lets you pin it yourself)",
        "es": "Ayúdame a anclar EthicalApp a la barra de tareas / Inicio (te muestra cómo al terminar; Windows solo deja que lo ancles tú)",
        "pt_BR": "Ajude-me a fixar o EthicalApp na barra de tarefas / Iniciar (mostra como depois; o Windows só deixa você fixar)",
        "fr": "M'aider à épingler EthicalApp à la barre des tâches / Démarrer (montre comment après l'installation ; Windows ne laisse que vous le faire)",
        "de": "Hilf mir, EthicalApp an Taskleiste / Start anzuheften (zeigt es nach dem Setup – Windows lässt das nur dich selbst tun)",
        "it": "Aiutami ad aggiungere EthicalApp alla barra delle applicazioni / Start (te lo mostra dopo; Windows lo consente solo a te)",
        "nl": "Help me EthicalApp aan de taakbalk / Start vast te maken (laat zien hoe na de installatie; alleen jij mag dat in Windows)",
        "pl": "Pomóż mi przypiąć EthicalApp do paska zadań / Start (pokaże jak po instalacji – Windows pozwala zrobić to tylko Tobie)",
        "tr": "EthicalApp'i görev çubuğuna / Başlat'a sabitlememe yardım et (kurulumdan sonra gösterir; Windows bunu yalnızca size bırakır)",
        "ru": "Помочь закрепить EthicalApp на панели задач / в «Пуске» (покажет как после установки — Windows позволяет это только вам)",
        "id": "Bantu saya menyematkan EthicalApp ke taskbar / Start (ditunjukkan setelah pemasangan; Windows hanya mengizinkan Anda sendiri)",
        "ja": "EthicalApp をタスクバー / スタートにピン留めするのを手伝う（セットアップ後に方法を表示。Windows では自分でしかピン留めできません）",
        "ko": "EthicalApp을 작업 표시줄 / 시작에 고정하도록 도와주기(설치 후 방법 안내 — Windows에서는 직접만 고정할 수 있음)",
        "zh_CN": "帮我把 EthicalApp 固定到任务栏 / 开始（安装后演示方法 — Windows 只允许你自己固定）"},
    "TaskRightClick": {
        "en": "Add right-click \"Open with Ethical …\" menu entries",
        "es": "Añadir al menú del clic derecho «Abrir con Ethical …»",
        "pt_BR": "Adicionar ao menu do botão direito “Abrir com Ethical …”",
        "fr": "Ajouter « Ouvrir avec Ethical … » au menu du clic droit",
        "de": "Rechtsklick-Einträge „Mit Ethical … öffnen“ hinzufügen",
        "it": "Aggiungi le voci «Apri con Ethical …» al menu del clic destro",
        "nl": "Items “Openen met Ethical …” aan het rechtsklikmenu toevoegen",
        "pl": "Dodaj pozycje „Otwórz w Ethical …” do menu prawego przycisku",
        "tr": "Sağ tıklama menüsüne “Ethical … ile aç” öğelerini ekle",
        "ru": "Добавить пункты «Открыть в Ethical …» в контекстное меню",
        "id": "Tambahkan item “Buka dengan Ethical …” ke menu klik kanan",
        "ja": "右クリック メニューに「Ethical … で開く」を追加",
        "ko": "오른쪽 클릭 메뉴에 “Ethical …(으)로 열기” 항목 추가",
        "zh_CN": "在右键菜单中添加“用 Ethical … 打开”"},
    "TaskSticky": {
        "en": "Start Ethical Sticky Notes when Windows starts (so your notes are always there)",
        "es": "Iniciar Ethical Sticky Notes con Windows (para que tus notas estén siempre ahí)",
        "pt_BR": "Iniciar o Ethical Sticky Notes com o Windows (para suas notas estarem sempre lá)",
        "fr": "Lancer Ethical Sticky Notes au démarrage de Windows (vos notes sont toujours là)",
        "de": "Ethical Sticky Notes mit Windows starten (damit deine Notizen immer da sind)",
        "it": "Avvia Ethical Sticky Notes all'avvio di Windows (così le note ci sono sempre)",
        "nl": "Ethical Sticky Notes met Windows starten (zodat je notities er altijd zijn)",
        "pl": "Uruchamiaj Ethical Sticky Notes z Windows (żeby notatki zawsze tam były)",
        "tr": "Ethical Sticky Notes'u Windows ile başlat (notlarınız hep orada olsun)",
        "ru": "Запускать Ethical Sticky Notes вместе с Windows (чтобы заметки всегда были на месте)",
        "id": "Mulai Ethical Sticky Notes bersama Windows (agar catatan Anda selalu ada)",
        "ja": "Windows の起動時に Ethical Sticky Notes を起動（メモがいつも表示されます）",
        "ko": "Windows 시작 시 Ethical Sticky Notes 실행(메모가 항상 보이도록)",
        "zh_CN": "随 Windows 启动 Ethical Sticky Notes（便笺随时都在）"},
    "TaskPlanner": {
        "en": "Start Ethical Planner when Windows starts, so reminders always pop up (recommended)",
        "es": "Iniciar Ethical Planner con Windows para que los recordatorios siempre aparezcan (recomendado)",
        "pt_BR": "Iniciar o Ethical Planner com o Windows para os lembretes sempre aparecerem (recomendado)",
        "fr": "Lancer Ethical Planner au démarrage de Windows pour que les rappels s'affichent toujours (recommandé)",
        "de": "Ethical Planner mit Windows starten, damit Erinnerungen immer erscheinen (empfohlen)",
        "it": "Avvia Ethical Planner all'avvio di Windows, così i promemoria compaiono sempre (consigliato)",
        "nl": "Ethical Planner met Windows starten, zodat herinneringen altijd verschijnen (aanbevolen)",
        "pl": "Uruchamiaj Ethical Planner z Windows, żeby przypomnienia zawsze się pojawiały (zalecane)",
        "tr": "Anımsatıcılar hep çıksın diye Ethical Planner'ı Windows ile başlat (önerilen)",
        "ru": "Запускать Ethical Planner вместе с Windows, чтобы напоминания всегда появлялись (рекомендуется)",
        "id": "Mulai Ethical Planner bersama Windows agar pengingat selalu muncul (disarankan)",
        "ja": "Windows の起動時に Ethical Planner を起動し、リマインダーが必ず表示されるようにする（推奨）",
        "ko": "미리 알림이 항상 나타나도록 Windows 시작 시 Ethical Planner 실행(권장)",
        "zh_CN": "随 Windows 启动 Ethical Planner，确保提醒总能弹出（推荐）"},
    "TaskSnip": {
        "en": "Keep Ethical Snip ready when Windows starts, so your snip shortcut always works",
        "es": "Tener Ethical Snip listo al iniciar Windows para que tu atajo funcione siempre",
        "pt_BR": "Deixar o Ethical Snip pronto ao iniciar o Windows para seu atalho sempre funcionar",
        "fr": "Garder Ethical Snip prêt au démarrage de Windows pour que votre raccourci marche toujours",
        "de": "Ethical Snip beim Windows-Start bereithalten, damit dein Tastenkürzel immer funktioniert",
        "it": "Tieni pronto Ethical Snip all'avvio di Windows, così la scorciatoia funziona sempre",
        "nl": "Ethical Snip klaarzetten bij het starten van Windows, zodat je sneltoets altijd werkt",
        "pl": "Miej Ethical Snip w gotowości od startu Windows, żeby skrót zawsze działał",
        "tr": "Kısayolunuz hep çalışsın diye Ethical Snip'i Windows başlarken hazır tut",
        "ru": "Держать Ethical Snip наготове с запуска Windows, чтобы сочетание клавиш всегда работало",
        "id": "Siapkan Ethical Snip saat Windows mulai agar pintasan Anda selalu berfungsi",
        "ja": "Windows の起動時に Ethical Snip を待機させ、ショートカットがいつでも使えるようにする",
        "ko": "바로 가기 키가 항상 작동하도록 Windows 시작 시 Ethical Snip 대기",
        "zh_CN": "随 Windows 启动时让 Ethical Snip 待命，确保截图快捷键随时可用"},
    "TaskClaude": {
        "en": "Connect the chosen apps to Claude (AI assistant) — works with Claude Code and Claude Desktop",
        "es": "Conectar las aplicaciones elegidas con Claude (asistente de IA): funciona con Claude Code y Claude Desktop",
        "pt_BR": "Conectar os aplicativos escolhidos ao Claude (assistente de IA): funciona com Claude Code e Claude Desktop",
        "fr": "Connecter les applications choisies à Claude (assistant IA) — fonctionne avec Claude Code et Claude Desktop",
        "de": "Die gewählten Apps mit Claude (KI-Assistent) verbinden – für Claude Code und Claude Desktop",
        "it": "Collega le app scelte a Claude (assistente IA): funziona con Claude Code e Claude Desktop",
        "nl": "De gekozen apps met Claude (AI-assistent) verbinden — werkt met Claude Code en Claude Desktop",
        "pl": "Połącz wybrane aplikacje z Claude (asystent AI) — działa z Claude Code i Claude Desktop",
        "tr": "Seçilen uygulamaları Claude'a (yapay zekâ asistanı) bağla — Claude Code ve Claude Desktop ile çalışır",
        "ru": "Подключить выбранные приложения к Claude (ИИ-помощник) — работает с Claude Code и Claude Desktop",
        "id": "Hubungkan aplikasi pilihan ke Claude (asisten AI) — berfungsi dengan Claude Code dan Claude Desktop",
        "ja": "選んだアプリを Claude（AI アシスタント）に接続 — Claude Code と Claude Desktop で使えます",
        "ko": "선택한 앱을 Claude(AI 도우미)에 연결 — Claude Code와 Claude Desktop에서 작동",
        "zh_CN": "将所选应用连接到 Claude（AI 助手）— 支持 Claude Code 和 Claude Desktop"},
    "RunClaude": {
        "en": "Connecting the apps to Claude...", "es": "Conectando las aplicaciones con Claude...",
        "pt_BR": "Conectando os aplicativos ao Claude...", "fr": "Connexion des applications à Claude...",
        "de": "Die Apps werden mit Claude verbunden...", "it": "Collegamento delle app a Claude...",
        "nl": "De apps worden met Claude verbonden...", "pl": "Łączenie aplikacji z Claude...",
        "tr": "Uygulamalar Claude'a bağlanıyor...", "ru": "Подключение приложений к Claude...",
        "id": "Menghubungkan aplikasi ke Claude...", "ja": "アプリを Claude に接続しています...",
        "ko": "앱을 Claude에 연결하는 중...", "zh_CN": "正在将应用连接到 Claude..."},
    "RunOpen": {
        "en": "Open EthicalApp", "es": "Abrir EthicalApp", "pt_BR": "Abrir o EthicalApp", "fr": "Ouvrir EthicalApp",
        "de": "EthicalApp öffnen", "it": "Apri EthicalApp", "nl": "EthicalApp openen", "pl": "Otwórz EthicalApp",
        "tr": "EthicalApp'i aç", "ru": "Открыть EthicalApp", "id": "Buka EthicalApp", "ja": "EthicalApp を開く",
        "ko": "EthicalApp 열기", "zh_CN": "打开 EthicalApp"},
    "RunOpenPin": {
        "en": "Open EthicalApp and show how to pin it to the taskbar",
        "es": "Abrir EthicalApp y mostrar cómo anclarlo a la barra de tareas",
        "pt_BR": "Abrir o EthicalApp e mostrar como fixá-lo na barra de tarefas",
        "fr": "Ouvrir EthicalApp et montrer comment l'épingler à la barre des tâches",
        "de": "EthicalApp öffnen und zeigen, wie man es an die Taskleiste anheftet",
        "it": "Apri EthicalApp e mostra come aggiungerlo alla barra delle applicazioni",
        "nl": "EthicalApp openen en laten zien hoe je het aan de taakbalk vastmaakt",
        "pl": "Otwórz EthicalApp i pokaż, jak przypiąć go do paska zadań",
        "tr": "EthicalApp'i aç ve görev çubuğuna nasıl sabitleneceğini göster",
        "ru": "Открыть EthicalApp и показать, как закрепить его на панели задач",
        "id": "Buka EthicalApp dan tunjukkan cara menyematkannya ke taskbar",
        "ja": "EthicalApp を開き、タスクバーへのピン留め方法を表示",
        "ko": "EthicalApp을 열고 작업 표시줄에 고정하는 방법 보기",
        "zh_CN": "打开 EthicalApp 并演示如何固定到任务栏"},
    "RunGuide": {
        "en": "Read the user guide", "es": "Leer la guía de uso", "pt_BR": "Ler o guia do usuário",
        "fr": "Lire le guide d'utilisation", "de": "Die Anleitung lesen", "it": "Leggi la guida",
        "nl": "De handleiding lezen", "pl": "Przeczytaj przewodnik", "tr": "Kullanım kılavuzunu oku",
        "ru": "Прочитать руководство", "id": "Baca panduan pengguna", "ja": "ユーザー ガイドを読む",
        "ko": "사용자 가이드 읽기", "zh_CN": "阅读使用指南"},
    # right-click menu labels in Explorer (%1 = app name)
    "OpenWith": {
        "en": "Open with %1", "es": "Abrir con %1", "pt_BR": "Abrir com %1", "fr": "Ouvrir avec %1",
        "de": "Mit %1 öffnen", "it": "Apri con %1", "nl": "Openen met %1", "pl": "Otwórz w %1", "tr": "%1 ile aç",
        "ru": "Открыть в %1", "id": "Buka dengan %1", "ja": "%1 で開く", "ko": "%1(으)로 열기", "zh_CN": "用 %1 打开"},
    "ConvertWith": {
        "en": "Convert / compress with Ethical Converter", "es": "Convertir / comprimir con Ethical Converter",
        "pt_BR": "Converter / comprimir com o Ethical Converter", "fr": "Convertir / compresser avec Ethical Converter",
        "de": "Mit Ethical Converter umwandeln / komprimieren", "it": "Converti / comprimi con Ethical Converter",
        "nl": "Converteren / comprimeren met Ethical Converter", "pl": "Konwertuj / kompresuj w Ethical Converter",
        "tr": "Ethical Converter ile dönüştür / sıkıştır", "ru": "Преобразовать / сжать в Ethical Converter",
        "id": "Konversi / kompres dengan Ethical Converter", "ja": "Ethical Converter で変換 / 圧縮",
        "ko": "Ethical Converter로 변환 / 압축", "zh_CN": "用 Ethical Converter 转换 / 压缩"},
}

_APPS_LIST = """  * Ethical PDF Editor
  * Ethical Document Editor
  * Ethical Spreadsheet Editor
  * Ethical Presentation Editor
  * Ethical Photo Editor
  * Ethical Converter
  * Ethical Database
  * Ethical Sticky Notes
  * Ethical Snip
  * Ethical Planner
  * Ethical Guide"""

# The welcome page (InfoBeforeFile). English is installer/welcome.txt.
WELCOME = {
    "es": f"""Bienvenido a EthicalApp

Aplicaciones de escritorio gratuitas para el trabajo de cada día — nuestras propias versiones de las herramientas que todo el mundo usa:

{_APPS_LIST}

En las páginas siguientes puedes elegir qué aplicaciones instalar, añadir accesos directos en el escritorio, añadir las entradas «Abrir con Ethical …» al menú del clic derecho y, si quieres, conectar las aplicaciones con Claude (un asistente de IA) para que las use por ti.

Conviene saber:
  * No hace falta contraseña de administrador: EthicalApp se instala solo para tu cuenta de usuario.
  * No se instala nada fuera de la carpeta de EthicalApp salvo los accesos directos y las entradas opcionales del clic derecho, y el desinstalador lo quita todo (Configuración > Aplicaciones > EthicalApp).
  * Tus archivos se quedan en tu equipo. Las aplicaciones funcionan sin conexión y nunca suben ni recopilan nada.
""",
    "pt_BR": f"""Bem-vindo ao EthicalApp

Aplicativos de desktop gratuitos para o trabalho do dia a dia — nossas próprias versões das ferramentas que todo mundo usa:

{_APPS_LIST}

Nas próximas páginas você escolhe quais aplicativos instalar, cria atalhos na área de trabalho, adiciona as entradas “Abrir com Ethical …” ao menu do botão direito e, se quiser, conecta os aplicativos ao Claude (um assistente de IA) para que ele os use por você.

Bom saber:
  * Não precisa de senha de administrador: o EthicalApp é instalado só para a sua conta de usuário.
  * Nada é instalado fora da pasta do EthicalApp além dos atalhos e das entradas opcionais do botão direito, e o desinstalador remove tudo (Configurações > Aplicativos > EthicalApp).
  * Seus arquivos ficam no seu computador. Os aplicativos funcionam offline e nunca enviam nem coletam nada.
""",
    "fr": f"""Bienvenue dans EthicalApp

Des applications de bureau gratuites pour le travail de tous les jours — nos propres versions des outils que tout le monde utilise :

{_APPS_LIST}

Dans les pages suivantes, vous pouvez choisir les applications à installer, créer des raccourcis sur le bureau, ajouter « Ouvrir avec Ethical … » au menu du clic droit et, si vous le souhaitez, connecter les applications à Claude (un assistant IA) pour qu'il les utilise à votre place.

Bon à savoir :
  * Aucun mot de passe administrateur n'est nécessaire : EthicalApp s'installe uniquement pour votre compte.
  * Rien n'est installé en dehors du dossier d'EthicalApp à part les raccourcis et les entrées facultatives du clic droit, et le programme de désinstallation retire tout (Paramètres > Applications > EthicalApp).
  * Vos fichiers restent sur votre ordinateur. Les applications fonctionnent hors ligne et n'envoient ni ne collectent jamais rien.
""",
    "de": f"""Willkommen bei EthicalApp

Kostenlose Desktop-Apps für die tägliche Arbeit – unsere eigenen Versionen der Programme, die alle jeden Tag nutzen:

{_APPS_LIST}

Auf den nächsten Seiten wählst du, welche Apps installiert werden, legst Desktop-Verknüpfungen an, fügst die Rechtsklick-Einträge „Mit Ethical … öffnen“ hinzu und kannst die Apps auf Wunsch mit Claude (einem KI-Assistenten) verbinden, damit er sie für dich bedient.

Gut zu wissen:
  * Kein Administratorpasswort nötig – EthicalApp wird nur für dein Benutzerkonto installiert.
  * Außer Verknüpfungen und den optionalen Rechtsklick-Einträgen wird nichts außerhalb des EthicalApp-Ordners installiert, und das Deinstallationsprogramm entfernt alles wieder (Einstellungen > Apps > EthicalApp).
  * Deine Dateien bleiben auf deinem Computer. Die Apps funktionieren offline und laden nie etwas hoch oder sammeln Daten.
""",
    "it": f"""Benvenuto in EthicalApp

App desktop gratuite per il lavoro di tutti i giorni — le nostre versioni degli strumenti che tutti usano ogni giorno:

{_APPS_LIST}

Nelle pagine successive puoi scegliere quali app installare, creare collegamenti sul desktop, aggiungere le voci «Apri con Ethical …» al menu del clic destro e, se vuoi, collegare le app a Claude (un assistente IA) perché le usi al posto tuo.

Buono a sapersi:
  * Non serve la password di amministratore: EthicalApp si installa solo per il tuo account.
  * Fuori dalla cartella di EthicalApp non viene installato nulla a parte i collegamenti e le voci facoltative del clic destro, e il programma di disinstallazione rimuove tutto (Impostazioni > App > EthicalApp).
  * I tuoi file restano sul tuo computer. Le app funzionano offline e non caricano né raccolgono mai nulla.
""",
    "nl": f"""Welkom bij EthicalApp

Gratis desktop-apps voor het dagelijkse werk — onze eigen versies van de programma's die iedereen elke dag gebruikt:

{_APPS_LIST}

Op de volgende pagina's kies je welke apps je installeert, maak je snelkoppelingen op het bureaublad, voeg je de items “Openen met Ethical …” toe aan het rechtsklikmenu en kun je de apps desgewenst met Claude (een AI-assistent) verbinden, zodat die ze voor je kan gebruiken.

Goed om te weten:
  * Geen beheerderswachtwoord nodig — EthicalApp wordt alleen voor jouw gebruikersaccount geïnstalleerd.
  * Behalve snelkoppelingen en de optionele rechtsklikitems wordt niets buiten de EthicalApp-map geïnstalleerd, en het verwijderprogramma haalt alles weer weg (Instellingen > Apps > EthicalApp).
  * Je bestanden blijven op je computer. De apps werken offline en uploaden of verzamelen nooit iets.
""",
    "pl": f"""Witaj w EthicalApp

Darmowe aplikacje na komputer do codziennej pracy — nasze własne wersje programów, których wszyscy używają na co dzień:

{_APPS_LIST}

Na kolejnych stronach wybierzesz aplikacje do zainstalowania, utworzysz skróty na pulpicie, dodasz pozycje „Otwórz w Ethical …” do menu prawego przycisku i — jeśli chcesz — połączysz aplikacje z Claude (asystentem AI), żeby mógł z nich korzystać za Ciebie.

Warto wiedzieć:
  * Hasło administratora nie jest potrzebne — EthicalApp instaluje się tylko dla Twojego konta.
  * Poza skrótami i opcjonalnymi pozycjami menu prawego przycisku nic nie jest instalowane poza folderem EthicalApp, a deinstalator usuwa wszystko (Ustawienia > Aplikacje > EthicalApp).
  * Twoje pliki zostają na Twoim komputerze. Aplikacje działają offline i nigdy niczego nie wysyłają ani nie zbierają.
""",
    "tr": f"""EthicalApp'e hoş geldiniz

Günlük işler için ücretsiz masaüstü uygulamaları — herkesin her gün kullandığı araçların kendi sürümlerimiz:

{_APPS_LIST}

Sonraki sayfalarda hangi uygulamaların yükleneceğini seçebilir, masaüstü kısayolları ekleyebilir, sağ tıklama menüsüne “Ethical … ile aç” öğelerini ekleyebilir ve isterseniz uygulamaları sizin yerinize kullanabilmesi için Claude'a (bir yapay zekâ asistanı) bağlayabilirsiniz.

Bilmekte fayda var:
  * Yönetici parolası gerekmez — EthicalApp yalnızca sizin kullanıcı hesabınız için yüklenir.
  * Kısayollar ve isteğe bağlı sağ tıklama öğeleri dışında EthicalApp klasörünün dışına hiçbir şey yüklenmez ve kaldırma programı her şeyi geri siler (Ayarlar > Uygulamalar > EthicalApp).
  * Dosyalarınız bilgisayarınızda kalır. Uygulamalar çevrimdışı çalışır ve hiçbir şeyi asla yüklemez ya da toplamaz.
""",
    "ru": f"""Добро пожаловать в EthicalApp

Бесплатные программы для повседневной работы — наши собственные версии инструментов, которыми все пользуются каждый день:

{_APPS_LIST}

На следующих страницах можно выбрать, какие приложения установить, создать ярлыки на рабочем столе, добавить пункты «Открыть в Ethical …» в контекстное меню и при желании подключить приложения к Claude (ИИ-помощнику), чтобы он мог работать с ними за вас.

Полезно знать:
  * Пароль администратора не нужен — EthicalApp устанавливается только для вашей учётной записи.
  * Кроме ярлыков и необязательных пунктов контекстного меню, ничего не устанавливается за пределами папки EthicalApp, а программа удаления убирает всё (Параметры > Приложения > EthicalApp).
  * Ваши файлы остаются на вашем компьютере. Приложения работают без интернета и никогда ничего не отправляют и не собирают.
""",
    "id": f"""Selamat datang di EthicalApp

Aplikasi desktop gratis untuk pekerjaan sehari-hari — versi kami sendiri dari alat yang dipakai semua orang setiap hari:

{_APPS_LIST}

Di halaman berikutnya Anda bisa memilih aplikasi yang dipasang, membuat pintasan desktop, menambahkan item “Buka dengan Ethical …” ke menu klik kanan, dan jika mau, menghubungkan aplikasi ke Claude (asisten AI) agar Claude bisa memakainya untuk Anda.

Perlu diketahui:
  * Tidak perlu kata sandi administrator — EthicalApp dipasang hanya untuk akun pengguna Anda.
  * Tidak ada yang dipasang di luar folder EthicalApp selain pintasan dan item klik kanan opsional, dan penghapus instalasi membersihkan semuanya (Pengaturan > Aplikasi > EthicalApp).
  * File Anda tetap di komputer Anda. Aplikasi bekerja tanpa internet dan tidak pernah mengunggah atau mengumpulkan apa pun.
""",
    "ja": f"""EthicalApp へようこそ

毎日の作業のための無料デスクトップ アプリです — 誰もが毎日使うツールを、私たちが自分で作り直しました:

{_APPS_LIST}

次のページでは、インストールするアプリの選択、デスクトップ ショートカットの作成、右クリック メニューへの「Ethical … で開く」の追加ができます。必要なら、アプリを Claude（AI アシスタント）に接続して、代わりに操作してもらうこともできます。

知っておいてほしいこと:
  * 管理者パスワードは不要です — EthicalApp はあなたのユーザー アカウントだけにインストールされます。
  * ショートカットと任意の右クリック項目のほかは EthicalApp フォルダーの外に何もインストールせず、アンインストーラーですべて削除されます（設定 > アプリ > EthicalApp）。
  * ファイルはあなたの PC に残ります。アプリはオフラインで動作し、何かをアップロードしたり収集したりすることはありません。
""",
    "ko": f"""EthicalApp에 오신 것을 환영합니다

일상 업무를 위한 무료 데스크톱 앱 — 모두가 매일 쓰는 도구를 저희가 직접 만든 버전입니다:

{_APPS_LIST}

다음 페이지에서 설치할 앱을 고르고, 바탕 화면 바로 가기를 만들고, 오른쪽 클릭 메뉴에 “Ethical …(으)로 열기” 항목을 추가할 수 있습니다. 원하면 앱을 Claude(AI 도우미)에 연결해 대신 사용하게 할 수도 있습니다.

알아 두세요:
  * 관리자 암호가 필요 없습니다 — EthicalApp은 내 사용자 계정에만 설치됩니다.
  * 바로 가기와 선택 사항인 오른쪽 클릭 항목 외에는 EthicalApp 폴더 밖에 아무것도 설치하지 않으며, 제거 프로그램이 모두 지웁니다(설정 > 앱 > EthicalApp).
  * 파일은 내 컴퓨터에 그대로 있습니다. 앱은 오프라인에서 작동하며 아무것도 업로드하거나 수집하지 않습니다.
""",
    "zh_CN": f"""欢迎使用 EthicalApp

免费的日常办公桌面应用 — 我们自己重做的、人人每天都在用的工具：

{_APPS_LIST}

在接下来的页面中，你可以选择要安装的应用、创建桌面快捷方式、在右键菜单中添加“用 Ethical … 打开”，还可以选择把应用连接到 Claude（AI 助手），让它替你操作。

须知：
  * 不需要管理员密码 — EthicalApp 只为你的用户帐户安装。
  * 除快捷方式和可选的右键菜单项外，不会在 EthicalApp 文件夹之外安装任何东西，卸载程序会把它们全部删除（设置 > 应用 > EthicalApp）。
  * 你的文件留在你的电脑上。这些应用离线工作，从不上传或收集任何内容。
""",
}
