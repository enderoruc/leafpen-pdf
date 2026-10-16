"""Turkish translations. Keys are the English source strings used with `tr()`."""

MESSAGES = {
    # --- core: documents ---
    "Wrong password.": "Parola yanlış.",
    "This PDF is password protected.": "Bu PDF parola korumalı.",
    "Could not write the file; another program may be using it.":
        "Dosyaya yazılamadı; başka bir program tarafından kullanılıyor olabilir.",
    "Could not open the PDF; the file is damaged or not a PDF. ({error})":
        "PDF açılamadı; dosya bozuk ya da PDF değil. ({error})",
    "The PDF has no pages.": "PDF hiç sayfa içermiyor.",
    "This page has pending redaction marks; editing text would apply them too. Remove those marks first.":
        "Bu sayfada uygulanmamış karartma (redaksiyon) işaretleri var; metin düzenlemek onları da uygular. "
        "Önce o işaretleri kaldırın.",
    "The text does not fit on the page. Choose a smaller size or a higher position.":
        "Metin sayfaya sığmıyor. Daha küçük punto ya da daha yukarıda bir konum seçin.",
    "The image file could not be read.": "Görsel dosyası okunamadı.",
    "All pages cannot be deleted; a PDF must keep at least one page.":
        "Tüm sayfalar silinemez; PDF en az bir sayfa içermelidir.",
    "Could not open the PDF to insert: {error}": "Eklenecek PDF açılamadı: {error}",
    "The selected file is not a PDF.": "Seçilen dosya bir PDF değil.",
    "The PDF to insert is password protected; remove its password first.":
        "Eklenecek PDF parola korumalı; önce parolasını kaldırın.",

    # --- core: signing ---
    "INVALID: The signed content was modified or the signature is corrupted.":
        "GEÇERSİZ: İmzalanan içerik değiştirilmiş ya da imza bozuk.",
    "WARNING: The signature is intact, but changes that are not permitted were made after signing.":
        "UYARI: İmza sağlam, ancak imzadan sonra belgede izin verilmeyen değişiklikler yapılmış.",
    "VALID: The document has not changed since it was signed and the signer was verified.":
        "GEÇERLİ: Belge imzalandığından beri değişmemiş ve imzalayan doğrulandı.",
    "INTEGRITY OK: The document has not changed since it was signed, but the signer's certificate "
    "does not chain to a trusted root (e.g. self-signed).":
        "BÜTÜNLÜK SAĞLAM: Belge imzalandığından beri değişmemiş, ancak imzalayanın sertifikası "
        "güvenilir bir kök sertifikaya bağlanmıyor (ör. kendinden imzalı).",
    " Only permitted changes (form filling, additional signatures) were made after signing.":
        " İmzadan sonra yalnızca izin verilen değişiklikler (form doldurma, ek imza) yapılmış.",
    "Name cannot be empty.": "Ad soyad boş olamaz.",
    "Password must be at least 4 characters.": "Parola en az 4 karakter olmalı.",
    "Could not read the certificate file: {error}": "Sertifika dosyası okunamadı: {error}",
    "Could not open the certificate: wrong password or not a valid .p12/.pfx file.":
        "Sertifika açılamadı: parola yanlış ya da dosya geçerli bir .p12/.pfx değil.",
    "The certificate expired on {date}.": "Sertifikanın süresi {date} tarihinde dolmuş.",
    "Digitally signed by:": "Dijital olarak imzalayan:",
    "Date: {when}": "Tarih: {when}",
    "Reason: {reason}": "Neden: {reason}",
    "A password is required for this PDF.": "PDF parolası gerekli.",
    "Signing failed: {error}": "İmzalama başarısız: {error}",
    "Could not read the signatures: {error}": "İmzalar okunamadı: {error}",
    "The signature could not be verified: {error}": "İmza doğrulanamadı: {error}",
    "Field: {name}": "Alan: {name}",
    "Signer: {name}": "İmzalayan: {name}",
    "Issued by: {name}": "Sertifikayı veren: {name}",
    "Certificate validity: {start} – {end}": "Sertifika geçerlilik: {start} – {end}",
    "SHA-256 fingerprint: {fingerprint}": "SHA-256 parmak izi: {fingerprint}",
    "Cryptographic integrity: intact": "Kriptografik bütünlük: sağlam",
    "Cryptographic integrity: BROKEN": "Kriptografik bütünlük: BOZUK",
    "Trust chain: chains to Windows root certificates": "Güven zinciri: Windows kök sertifikalarına bağlanıyor",
    "Trust chain: does not chain to a trusted root": "Güven zinciri: bağlanmıyor",
    "Revocation (CRL/OCSP) check: not performed (working offline)":
        "İptal (CRL/OCSP) denetimi: yapılmadı (çevrimdışı çalışılıyor)",

    # --- main window ---
    "PDF documents (*.pdf)": "PDF belgeleri (*.pdf)",
    "Browse: drag to scroll, Ctrl+wheel to zoom.":
        "Gezinme: sürükleyerek kaydırın, Ctrl+tekerlek ile yakınlaştırın.",
    "Add text: click where the text should start.": "Metin ekle: metnin başlayacağı yere tıklayın.",
    "Edit text: click the line you want to change.": "Metin düzenle: değiştirmek istediğiniz satıra tıklayın.",
    "Highlight: drag across the text to highlight.": "Vurgula: vurgulanacak metnin üzerinden sürükleyin.",
    "Pen: draw freely.": "Kalem: serbestçe çizin.",
    "Image: draw or click where the image should go.":
        "Görsel: görselin yerleşeceği alanı çizin ya da tıklayın.",
    "Signature: draw or click where the signature should go.":
        "El imzası: imzanın yerleşeceği alanı çizin ya da tıklayın.",
    "Erase: click an annotation, stamp, note or form field to remove it.":
        "Sil: kaldırmak istediğiniz açıklamaya, damgaya, nota ya da form alanına tıklayın.",
    "Digital signature: draw or click where the signature should appear (Esc: cancel).":
        "Dijital imza: imzanın görüneceği alanı çizin ya da tıklayın (Esc: iptal).",
    "Verify signatures": "İmzaları doğrula",
    "Press Ctrl+O to open a PDF or drag a file here.":
        "PDF açmak için Ctrl+O'ya basın ya da dosyayı buraya sürükleyin.",
    "Rotate left (selected pages)": "Sola döndür (seçili sayfalar)",
    "Rotate right (selected pages)": "Sağa döndür (seçili sayfalar)",
    "Move up": "Yukarı taşı",
    "Move down": "Aşağı taşı",
    "Delete selected pages": "Seçili sayfaları sil",
    "Pages": "Sayfalar",
    "Form fields": "Form alanları",
    "Open…": "Aç…",
    "Save": "Kaydet",
    "Save as…": "Farklı kaydet…",
    "Insert pages from another PDF…": "Başka PDF'den sayfa ekle…",
    "Save selected pages as a separate PDF…": "Seçili sayfaları ayrı PDF olarak kaydet…",
    "Print…": "Yazdır…",
    "Quit": "Çıkış",
    "Undo": "Geri al",
    "Redo": "Yinele",
    "Zoom in": "Yakınlaştır",
    "Zoom out": "Uzaklaştır",
    "Fit width": "Genişliğe sığdır",
    "Actual size": "Gerçek boyut",
    "My signatures…": "El imzalarım…",
    "Sign digitally…": "Dijital olarak imzala…",
    "Create new digital ID…": "Yeni dijital kimlik oluştur…",
    "About": "Hakkında",
    "Browse": "Gezin",
    "Add text": "Metin ekle",
    "Edit text": "Metin düzenle",
    "Highlight": "Vurgula",
    "Pen": "Kalem",
    "Image": "Görsel",
    "Signature": "El imzası",
    "Erase": "Sil",
    "&File": "&Dosya",
    "E&dit": "Dü&zen",
    "&View": "&Görünüm",
    "&Signatures": "İ&mzalar",
    "&Help": "&Yardım",
    "&Language": "&Dil",
    "System default": "Sistem dili",
    "Tools": "Araçlar",
    " Color ": " Renk ",
    " Width ": " Kalınlık ",
    "Untitled": "Adsız",
    "Page {page} / {total}": "Sayfa {page} / {total}",
    "{percent}%": "%{percent}",
    "There are unsaved changes. Do you want to save them?":
        "Kaydedilmemiş değişiklikler var. Kaydetmek ister misiniz?",
    "Open PDF": "PDF aç",
    "Wrong password. This PDF is password protected. Enter the password:":
        "Parola yanlış. Bu PDF parola korumalı. Parolayı girin:",
    "This PDF is password protected. Enter the password:": "Bu PDF parola korumalı. Parolayı girin:",
    "Password": "Parola",
    "Could not read the file: {error}": "Dosya okunamadı: {error}",
    "This document contains digital signatures. If you edit and save it, the existing signatures "
    "will appear invalid.":
        "Bu belge dijital imza içeriyor. Değişiklik yapıp kaydederseniz mevcut imzalar geçersiz görünür.",
    "This document is digitally signed. In the file saved with your changes the existing signatures "
    "will appear invalid.\n\nUsing 'Save as' is recommended to keep the original signed file. Continue?":
        "Bu belge dijital olarak imzalanmış. Değişikliklerle kaydedilen dosyada mevcut imzalar geçersiz "
        "görünecek.\n\nÖzgün imzalı dosyayı korumak için 'Farklı kaydet' kullanmanız önerilir. "
        "Devam edilsin mi?",
    "Save as": "Farklı kaydet",
    "Could not save: {error}": "Kaydedilemedi: {error}",
    "Saved: {path}": "Kaydedildi: {path}",
    "PDF to insert": "Eklenecek PDF",
    "pages": "sayfalar",
    "{base}_page_{number}.pdf": "{base}_sayfa_{number}.pdf",
    "Save pages": "Sayfaları kaydet",
    "{count} page(s) saved: {path}": "{count} sayfa kaydedildi: {path}",
    "The printer could not be started.": "Yazıcı başlatılamadı.",
    "Delete {count} pages?": "{count} sayfa silinsin mi?",
    "Delete page {number}?": "{number}. sayfa silinsin mi?",
    "There is no editable text here. (Text on scanned pages is an image and cannot be edited.)":
        "Burada düzenlenebilir metin yok. (Taranmış sayfalardaki yazılar görüntüdür; düzenlenemez.)",
    "There is no annotation to erase here. Use Undo (Ctrl+Z) for added text and images.":
        "Burada silinecek açıklama yok. Eklenen metin ve görseller için Geri al'ı (Ctrl+Z) kullanın.",
    "Choose image": "Görsel seç",
    "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.heic *.heif)":
        "Görseller (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.heic *.heif)",
    "Digital ID created:\n{path}\n\nBack up this file and its password in a safe place.":
        "Dijital kimlik oluşturuldu:\n{path}\n\nBu dosyayı ve parolasını güvenli bir yerde yedekleyin.",
    "The document has existing signatures and unsaved changes. If you continue, the existing "
    "signatures will appear invalid. Continue?":
        "Belgede mevcut imzalar var ve kaydedilmemiş değişiklikler yapıldı. Devam ederseniz mevcut "
        "imzalar geçersiz görünecek. Devam edilsin mi?",
    "document": "belge",
    "{base}_signed.pdf": "{base}_imzali.pdf",
    "Save signed PDF": "İmzalı PDF'i kaydet",
    "Signed and saved: {path}": "İmzalandı ve kaydedildi: {path}",
    "Verification was performed on the saved version on disk (excluding unsaved changes).":
        "Doğrulama, diskteki kayıtlı sürüm üzerinde yapıldı (kaydedilmemiş değişiklikler hariç).",
    "Restart the application to apply the new language.":
        "Yeni dili uygulamak için uygulamayı yeniden başlatın.",
    "An unexpected error occurred.": "Beklenmeyen bir hata oluştu.",

    # --- panels ---
    "Apply form": "Formu uygula",
    "— none selected —": "— seçilmedi —",
    "(p. {page})": "(s. {page})",

    # --- dialogs ---
    "Choose color": "Renk seç",
    "Text:": "Metin:",
    "Size:": "Punto:",
    "New handwritten signature": "Yeni el imzası",
    "Clear": "Temizle",
    "Sign with your mouse, pen or touch screen:": "Fare, kalem ya da dokunmatik ekranla imzanızı atın:",
    "Draw": "Çiz",
    "Type": "Yaz",
    "Your full name": "Adınız Soyadınız",
    "Full name:": "Ad soyad:",
    "Font:": "Yazı tipi:",
    "Choose a scanned signature image (PNG/JPG).": "Taranmış imza görseli seçin (PNG/JPG).",
    "Make the paper background transparent": "Kâğıt arka planını şeffaf yap",
    "Choose image…": "Görsel seç…",
    "Signature image": "İmza görseli",
    "Images (*.png *.jpg *.jpeg *.bmp *.heic *.heif)": "Görseller (*.png *.jpg *.jpeg *.bmp *.heic *.heif)",
    "The image could not be read.": "Görsel okunamadı.",
    "Create a signature first.": "Önce bir imza oluşturun.",
    "My signatures": "El imzalarım",
    "New signature…": "Yeni imza…",
    "Delete": "Sil",
    "Select": "Seç",
    "Signatures are stored only on this computer.": "İmzalar yalnızca bu bilgisayarda saklanır.",
    "Delete signature": "İmzayı sil",
    "Delete the selected signature?": "Seçili imza silinsin mi?",
    "Select a signature or create a new one.": "Bir imza seçin ya da yeni imza oluşturun.",
    "New digital ID": "Yeni dijital kimlik",
    " year(s)": " yıl",
    "A self-signed certificate will be created. It proves the document has not changed since it was "
    "signed, but the other party will only see your identity as verified if they trust your "
    "certificate. For legally recognised signatures, use a .pfx/.p12 file from an authorised provider.":
        "Kendinden imzalı bir sertifika oluşturulur. Belgenin imzadan sonra değişmediğini kanıtlar; "
        "ancak karşı taraf kimliğinizi ancak sertifikanıza güvenirse doğrulanmış görür. "
        "Resmî geçerlilik (e-İmza/NES) için yetkili sağlayıcıdan aldığınız .pfx/.p12 dosyasını kullanın.",
    "Create and save…": "Oluştur ve kaydet…",
    "Full name*:": "Ad soyad*:",
    "Email:": "E-posta:",
    "Organization:": "Kurum:",
    "Password*:": "Parola*:",
    "Repeat password*:": "Parola (tekrar)*:",
    "Validity:": "Geçerlilik:",
    "Full name is required.": "Ad soyad gerekli.",
    "Passwords do not match.": "Parolalar eşleşmiyor.",
    "Save digital ID": "Dijital kimliği kaydet",
    "Digital ID (*.p12)": "Dijital kimlik (*.p12)",
    "Sign digitally": "Dijital olarak imzala",
    ".p12 / .pfx file": ".p12 / .pfx dosyası",
    "Browse…": "Gözat…",
    "Create new…": "Yeni oluştur…",
    "e.g. I approve the contract": "örn. Sözleşmeyi onaylıyorum",
    "Visible signature (draw an area on the page to place it)":
        "Görünür imza (sayfada alan çizerek yerleştir)",
    "Also show my handwritten signature": "El imzamı da göster",
    "First create a handwritten signature with Signatures › My signatures…":
        "Önce İmzalar › El imzalarım… ile bir el imzası oluşturun.",
    "Sign": "İmzala",
    "Digital ID:": "Dijital kimlik:",
    "Password:": "Parola:",
    "Reason:": "Neden:",
    "Location:": "Yer:",
    "Digital ID": "Dijital kimlik",
    "Digital ID (*.p12 *.pfx)": "Dijital kimlik (*.p12 *.pfx)",
    "Signature verification": "İmza doğrulama",
    "This document has no digital signatures.": "Bu belgede dijital imza yok.",
    "Signed at: {when}": "İmza zamanı: {when}",
    "unknown": "bilinmiyor",
    "An offline, free PDF editor and signer. No data ever leaves your computer.":
        "Çevrimdışı ve ücretsiz PDF düzenleyici ve imzalayıcı. Hiçbir veri bilgisayarınızdan çıkmaz.",
    "Open-source components used:": "Kullanılan açık kaynak bileşenler:",

    # --- core: search, redaction, bookmarks, layout, forms ---
    "A bookmark needs a title.": "Yer iminin bir başlığı olmalı.",
    "The crop area is too small.": "Kırpma alanı çok küçük.",
    "The crop area lies outside page {number}.": "Kırpma alanı {number}. sayfanın dışında kalıyor.",
    "Enter the watermark text.": "Filigran metnini girin.",
    "Enter at least one header or footer text.": "En az bir üstbilgi ya da altbilgi metni girin.",
    "The header or footer text does not fit on page {number}.":
        "Üstbilgi ya da altbilgi metni {number}. sayfaya sığmıyor.",
    "The paragraph does not fit on the page. Shorten the text or choose a smaller size.":
        "Paragraf sayfaya sığmıyor. Metni kısaltın ya da daha küçük punto seçin.",
    "The field needs a name.": "Alanın bir adı olmalı.",
    "Field names cannot contain a dot.": "Alan adları nokta içeremez.",
    "A field named \"{name}\" already exists.": "\"{name}\" adlı bir alan zaten var.",
    "Enter at least one option for the list.": "Liste için en az bir seçenek girin.",
    "The field area is too small.": "Alan çok küçük.",

    # --- main window: new tools and menus ---
    "Edit paragraph: click the paragraph you want to change.":
        "Paragraf düzenle: değiştirmek istediğiniz paragrafa tıklayın.",
    "Rectangle: drag to draw.": "Dikdörtgen: sürükleyerek çizin.",
    "Ellipse: drag to draw.": "Elips: sürükleyerek çizin.",
    "Line: drag from start to end.": "Çizgi: başlangıçtan bitişe sürükleyin.",
    "Arrow: drag from the tail to the tip.": "Ok: kuyruktan uca doğru sürükleyin.",
    "Note: click to add a sticky note, or click a note to edit it.":
        "Not: yapışkan not eklemek için tıklayın ya da düzenlemek için bir nota tıklayın.",
    "Stamp: draw or click where the stamp should go.": "Damga: damganın yerleşeceği alanı çizin ya da tıklayın.",
    "Redact: drag over the content to remove. Apply the marks with Document › Apply redactions.":
        "Karart: kaldırılacak içeriğin üzerine sürükleyin. İşaretleri Belge › Karartmaları uygula ile uygulayın.",
    "Crop: drag the area to keep (applies to the selected pages).":
        "Kırp: korunacak alanı sürükleyerek çizin (seçili sayfalara uygulanır).",
    "Form field: draw or click where the field should go.": "Form alanı: alanın yerleşeceği yeri çizin ya da tıklayın.",
    "Bookmarks": "Yer imleri",
    "Find…": "Bul…",
    "Export pages as images…": "Sayfaları görsel olarak dışa aktar…",
    "Reduce file size…": "Dosya boyutunu küçült…",
    "Apply redactions…": "Karartmaları uygula…",
    "Add watermark…": "Filigran ekle…",
    "Add header and footer…": "Üstbilgi ve altbilgi ekle…",
    "Remove crop (selected pages)": "Kırpmayı kaldır (seçili sayfalar)",
    "Edit line": "Satır düzenle",
    "Edit paragraph": "Paragraf düzenle",
    "Rectangle": "Dikdörtgen",
    "Ellipse": "Elips",
    "Line": "Çizgi",
    "Arrow": "Ok",
    "Note": "Not",
    "Stamp": "Damga",
    "Redact": "Karart",
    "Crop pages": "Sayfaları kırp",
    "Add form field": "Form alanı ekle",
    "&Comment": "&Yorum",
    "&Document": "&Belge",
    "Shapes": "Şekiller",
    "{count} area(s) are marked for redaction but not applied yet. The marked content is still in the file "
    "and can be read by anyone.\n\nApply the redactions before saving?":
        "{count} alan karartma için işaretlendi ama henüz uygulanmadı. İşaretli içerik hâlâ dosyanın içinde ve "
        "herkes tarafından okunabilir.\n\nKaydetmeden önce karartmalar uygulansın mı?",
    "{count} match(es) marked for redaction. Apply them with Document › Apply redactions.":
        "{count} eşleşme karartma için işaretlendi. Belge › Karartmaları uygula ile uygulayın.",
    "Add bookmark": "Yer imi ekle",
    "Bookmark title:": "Yer imi başlığı:",
    "Page {number}": "Sayfa {number}",
    "Rename bookmark": "Yer imini yeniden adlandır",
    "Delete the bookmark \"{title}\" and the bookmarks under it?":
        "\"{title}\" yer imi ve altındaki yer imleri silinsin mi?",
    "There are no redaction marks. Mark areas with the Redact tool or with Find › Mark all for redaction first.":
        "Karartma işareti yok. Önce Karart aracıyla ya da Bul › Tümünü karartma için işaretle ile alan işaretleyin.",
    "Permanently remove the text, images and drawings under {count} redaction mark(s)? The areas are filled "
    "with black. Once the file is saved this cannot be undone.":
        "{count} karartma işaretinin altındaki metin, görsel ve çizimler kalıcı olarak kaldırılsın mı? Alanlar "
        "siyahla doldurulur. Dosya kaydedildikten sonra bu işlem geri alınamaz.",
    "Redactions applied. Save the document to keep the result.":
        "Karartmalar uygulandı. Sonucu korumak için belgeyi kaydedin.",
    "Save compressed copy": "Sıkıştırılmış kopyayı kaydet",
    "{base}_compressed.pdf": "{base}_sikistirilmis.pdf",
    "Compressed copy saved:\n{path}\n\n{before} → {after} ({percent}% smaller)":
        "Sıkıştırılmış kopya kaydedildi:\n{path}\n\n{before} → {after} (%{percent} daha küçük)",
    "Compressed copy saved:\n{path}\n\nSize: {after}": "Sıkıştırılmış kopya kaydedildi:\n{path}\n\nBoyut: {after}",
    "PNG images (*.png)": "PNG görselleri (*.png)",
    "JPEG images (*.jpg)": "JPEG görselleri (*.jpg)",
    "Export pages as images": "Sayfaları görsel olarak dışa aktar",
    "{count} image(s) saved, e.g. {path}": "{count} görsel kaydedildi, ör. {path}",

    # --- panels: bookmarks, find, forms ---
    "Add": "Ekle",
    "Add a bookmark to the current page": "Geçerli sayfaya yer imi ekle",
    "Rename": "Yeniden adlandır",
    "No bookmarks. Use Add to bookmark the current page.":
        "Yer imi yok. Geçerli sayfayı yer imlerine eklemek için Ekle'yi kullanın.",
    "Find in document": "Belgede bul",
    "Previous (Shift+Enter)": "Önceki (Shift+Enter)",
    "Next (Enter)": "Sonraki (Enter)",
    "Mark all for redaction": "Tümünü karartma için işaretle",
    "Mark every match for redaction. Nothing is removed until you apply the redactions.":
        "Tüm eşleşmeleri karartma için işaretler. Karartmaları uygulayana kadar hiçbir şey kaldırılmaz.",
    "Close (Esc)": "Kapat (Esc)",
    "No matches": "Eşleşme yok",
    "{current} of {total}": "{current} / {total}",
    "Add field…": "Alan ekle…",
    "Draw a new form field on the page": "Sayfaya yeni bir form alanı çizin",

    # --- dialogs: new tools ---
    "Note text (leave empty to delete the note)": "Not metni (notu silmek için boş bırakın)",
    "Note text": "Not metni",
    "APPROVED": "ONAYLANDI",
    "REJECTED": "REDDEDİLDİ",
    "DRAFT": "TASLAK",
    "CONFIDENTIAL": "GİZLİ",
    "FINAL": "NİHAİ",
    "RECEIVED": "TESLİM ALINDI",
    "PAID": "ÖDENDİ",
    "COPY": "KOPYA",
    "FOR COMMENT": "GÖRÜŞE",
    "VOID": "İPTAL",
    "Color:": "Renk:",
    "Enter the stamp text.": "Damga metnini girin.",
    "New form field": "Yeni form alanı",
    "Text": "Metin",
    "Multi-line text": "Çok satırlı metin",
    "Checkbox": "Onay kutusu",
    "Drop-down list": "Açılır liste",
    "List box": "Liste kutusu",
    "One option per line": "Her satıra bir seçenek",
    "Options:": "Seçenekler:",
    "Type:": "Tür:",
    "Name:": "Ad:",
    "All pages ({count})": "Tüm sayfalar ({count})",
    "Current page ({number})": "Geçerli sayfa ({number})",
    "Selected pages ({count})": "Seçili sayfalar ({count})",
    "Watermark": "Filigran",
    "Angle:": "Açı:",
    "Opacity:": "Opaklık:",
    "Place behind the page content": "Sayfa içeriğinin arkasına yerleştir",
    "The text is shrunk if it does not fit on a page.": "Metin sayfaya sığmazsa küçültülür.",
    "Pages:": "Sayfalar:",
    "Header and footer": "Üstbilgi ve altbilgi",
    "Header, left:": "Üstbilgi, sol:",
    "Header, center:": "Üstbilgi, orta:",
    "Header, right:": "Üstbilgi, sağ:",
    "Footer, left:": "Altbilgi, sol:",
    "Footer, center:": "Altbilgi, orta:",
    "Footer, right:": "Altbilgi, sağ:",
    "Page {page} of {pages}": "Sayfa {page} / {pages}",
    "{page} is replaced with the page number, {pages} with the page count and {date} with today's date.":
        "{page} sayfa numarasıyla, {pages} sayfa sayısıyla, {date} bugünün tarihiyle değiştirilir.",
    "Margin:": "Kenar boşluğu:",
    "Reduce file size": "Dosya boyutunu küçült",
    "High quality (images up to 200 dpi)": "Yüksek kalite (görseller en fazla 200 dpi)",
    "Balanced (images up to 150 dpi)": "Dengeli (görseller en fazla 150 dpi)",
    "Smallest file (images up to 96 dpi)": "En küçük dosya (görseller en fazla 96 dpi)",
    "A compressed copy is saved as a new file; the open document is not changed. Images are resampled and "
    "re-compressed, fonts are reduced to the characters used, and unused data is removed.":
        "Sıkıştırılmış kopya yeni bir dosya olarak kaydedilir; açık belge değişmez. Görseller yeniden "
        "örneklenip sıkıştırılır, yazı tipleri kullanılan karakterlere indirgenir ve kullanılmayan veriler "
        "kaldırılır.",
    "The digital signatures in this document will not be valid in the compressed copy.":
        "Bu belgedeki dijital imzalar sıkıştırılmış kopyada geçerli olmayacak.",
    "Quality:": "Kalite:",
    "Save copy…": "Kopyayı kaydet…",
    "Format:": "Biçim:",
    "Resolution:": "Çözünürlük:",
    "Export…": "Dışa aktar…",

    # --- on-page text editing ---
    "Font": "Yazı tipi",
    "Size": "Punto",
    "Bold (Ctrl+B)": "Kalın (Ctrl+B)",
    "Italic (Ctrl+I)": "İtalik (Ctrl+I)",
    "Align left": "Sola hizala",
    "Center": "Ortala",
    "Align right": "Sağa hizala",
    "Justify": "İki yana yasla",
    "Line spacing": "Satır aralığı",
    "Apply (Ctrl+Enter)": "Uygula (Ctrl+Enter)",
    "Cancel (Esc)": "İptal (Esc)",
    "Drag to change the width": "Genişliği değiştirmek için sürükleyin",
    "Type the text. Ctrl+Enter or a click outside the box adds it; Esc cancels.":
        "Metni yazın. Ctrl+Enter ya da kutunun dışına tıklamak ekler; Esc iptal eder.",
    "Edit the line. Ctrl+Enter or a click outside the box applies it; Esc cancels. Leave it empty to delete "
    "the line.":
        "Satırı düzenleyin. Ctrl+Enter ya da kutunun dışına tıklamak uygular; Esc iptal eder. Satırı silmek "
        "için boş bırakın.",
    "Edit the paragraph. Ctrl+Enter or a click outside the box applies it; Esc cancels. Drag the blue handle "
    "to change the width.":
        "Paragrafı düzenleyin. Ctrl+Enter ya da kutunun dışına tıklamak uygular; Esc iptal eder. Genişliği "
        "değiştirmek için mavi tutamacı sürükleyin.",
    "The paragraph now overlaps the text below it. Make it shorter or wider, or undo with Ctrl+Z.":
        "Paragraf artık alttaki metnin üzerine taşıyor. Kısaltın ya da genişletin veya Ctrl+Z ile geri alın.",

    # --- select tool and properties bar ---
    "Select: click a shape, stamp, note, image, form field or paragraph to move, resize or restyle it.":
        "Seç: taşımak, boyutlandırmak ya da biçimini değiştirmek için bir şekle, damgaya, nota, görsele, form "
        "alanına veya paragrafa tıklayın.",
    "Properties": "Özellikler",
    "New items:": "Yeni öğeler:",
    "Selected {kind}:": "Seçili {kind}:",
    " Fill ": " Dolgu ",
    " Line ": " Çizgi ",
    " Opacity ": " Opaklık ",
    "Fill color of rectangles and ellipses": "Dikdörtgen ve elipslerin dolgu rengi",
    "No fill": "Dolgu yok",
    "Choose fill color…": "Dolgu rengi seç…",
    "Fill color": "Dolgu rengi",
    "Solid": "Düz",
    "Dashed": "Kesikli",
    "Drag to move, drag the handles to resize. Delete removes it; double-click edits it.":
        "Taşımak için sürükleyin, boyutlandırmak için tutamaçları sürükleyin. Delete siler; çift tıklama "
        "düzenler.",
    "This object cannot be moved here; you can change its color or delete it.":
        "Bu nesne burada taşınamaz; rengini değiştirebilir ya da silebilirsiniz.",
    "This object cannot be moved.": "Bu nesne taşınamaz.",
    "The object would be too small.": "Nesne çok küçük olur.",
    "This image cannot be moved or removed.": "Bu görsel taşınamaz ya da kaldırılamaz.",
    "paragraph": "paragraf",
    "image": "görsel",
    "form field": "form alanı",
    "rectangle": "dikdörtgen",
    "ellipse": "elips",
    "line": "çizgi",
    "drawing": "çizim",
    "stamp": "damga",
    "note": "not",
    "text box": "metin kutusu",
    "highlight": "vurgu",
    "annotation": "açıklama",

    # --- note icons ---
    "Icon:": "Simge:",
    "Comment": "Yorum",
    "Help": "Yardım",
    "Key": "Anahtar",
    "Insertion mark": "Ekleme işareti",
    "Paragraph": "Paragraf",
    "New paragraph": "Yeni paragraf",

    # --- toolbar, zoom, recent files ---
    "Insert": "Ekle",
    "Zoom": "Yakınlaştırma",
    "Nothing selected": "Seçili öğe yok",
    "Open &recent": "&Son açılanlar",
    "No recent files": "Son açılan dosya yok",
    "Clear list": "Listeyi temizle",
    "Recent files": "Son açılanlar",
    "The file no longer exists:\n{path}\n\nIt was removed from the list.":
        "Dosya artık yok:\n{path}\n\nListeden kaldırıldı.",

    # --- command palette ---
    "Command palette…": "Komut paleti…",
    "Find any command by typing part of its name": "Herhangi bir komutu adının bir kısmını yazarak bulun",
    "Type a command…": "Bir komut yazın…",
    "Not available now (open a document first).": "Şu anda kullanılamaz (önce bir belge açın).",

    # --- Explorer "Open with" ---
    "Show in “Open with” for PDF files": "PDF dosyaları için “Birlikte aç” listesinde göster",
    "Available in the packaged app (LeafpenPDF.exe).": "Paketlenmiş uygulamada (LeafpenPDF.exe) kullanılabilir.",
    "{name} now appears under Open with for PDF files. Your default PDF program is unchanged.":
        "{name} artık PDF dosyaları için Birlikte aç listesinde. Varsayılan PDF programınız değişmedi.",
    "{name} was removed from Open with.": "{name}, Birlikte aç listesinden kaldırıldı.",
    "Windows did not allow the change: {error}": "Windows bu değişikliğe izin vermedi: {error}",
    "Shortcut on the desktop": "Masaüstünde kısayol",
    "Shortcut in the Start menu": "Başlat menüsünde kısayol",
    "Shortcut created: {path}": "Kısayol oluşturuldu: {path}",
    "Shortcut removed.": "Kısayol kaldırıldı.",

    # --- tools: merge, split, images to PDF, passwords, repair ---
    "&Tools": "&Araçlar",
    "Merge PDFs…": "PDF'leri birleştir…",
    "Merge PDFs": "PDF'leri birleştir",
    "Merge…": "Birleştir…",
    "Split into separate PDFs…": "Ayrı PDF'lere böl…",
    "Split into separate PDFs": "Ayrı PDF'lere böl",
    "Split…": "Böl…",
    "Create PDF from images…": "Görsellerden PDF oluştur…",
    "Create PDF from images": "Görsellerden PDF oluştur",
    "Create PDF…": "PDF oluştur…",
    "Protect with password…": "Parolayla koru…",
    "Protect with password": "Parolayla koru",
    "Remove password…": "Parolayı kaldır…",
    "Save a copy without the password and permission restrictions":
        "Parola ve izin kısıtlamaları olmadan bir kopya kaydet",
    "Repair a damaged PDF…": "Bozuk bir PDF'i onar…",
    "Choose a different file name; the new file cannot replace the original.":
        "Farklı bir dosya adı seçin; yeni dosya orijinalin yerine kaydedilemez.",
    "Open it now?": "Şimdi açılsın mı?",
    "Choose at least two PDFs to merge.": "Birleştirmek için en az iki PDF seçin.",
    "Choose at least one image.": "En az bir görsel seçin.",
    "Could not open {name}; the file is damaged or not a PDF.": "{name} açılamadı; dosya bozuk ya da PDF değil.",
    "{name} is password protected. Open it and remove its password first.":
        "{name} parola korumalı. Önce dosyayı açıp parolasını kaldırın.",
    "This PDF is password protected. Open it and remove its password first.":
        "Bu PDF parola korumalı. Önce dosyayı açıp parolasını kaldırın.",
    "Could not read the image {name}.": "{name} görseli okunamadı.",
    "The file could not be recovered; too little of it is readable as a PDF.":
        "Dosya kurtarılamadı; PDF olarak okunabilen kısmı çok az.",
    "“{part}” is not a page range. Use for example 1-3, 5, 8-.":
        "“{part}” geçerli bir sayfa aralığı değil. Örneğin 1-3, 5, 8- şeklinde yazın.",
    "“{part}” is outside the document's pages (1–{count}).": "“{part}” belgenin sayfaları dışında (1–{count}).",
    "Enter at least one page range.": "En az bir sayfa aralığı girin.",
    "Set a password to open the file, or turn off at least one permission.":
        "Dosyayı açmak için bir parola belirleyin ya da en az bir izni kapatın.",
    "Add files…": "Dosya ekle…",
    "Add files": "Dosya ekle",
    "Remove": "Kaldır",
    "Move up": "Yukarı taşı",
    "Move down": "Aşağı taşı",
    "Drag files to change their order, or drop files from Explorer here.":
        "Sırayı değiştirmek için dosyaları sürükleyin ya da Gezgin'den buraya bırakın.",
    "{name} (open document)": "{name} (açık belge)",
    "Add a bookmark for each file": "Her dosya için bir yer imi ekle",
    "Images ({patterns})": "Görseller ({patterns})",
    "Same as the image": "Görselle aynı",
    "Automatic (follows the image)": "Otomatik (görsele göre)",
    "Portrait": "Dikey",
    "Landscape": "Yatay",
    "None": "Yok",
    "Small": "Küçük",
    "Large": "Büyük",
    "Page size:": "Sayfa boyutu:",
    "Orientation:": "Yönlendirme:",
    "Margin:": "Kenar boşluğu:",
    "Every page into its own file": "Her sayfa ayrı bir dosyaya",
    "A new file every": "Her",
    " pages": " sayfada bir yeni dosya",
    "Page ranges:": "Sayfa aralıkları:",
    "e.g. 1-3, 5, 8-": "örn. 1-3, 5, 8-",
    "Each range becomes a separate file; “8-” runs to the last page. The open document is not changed.":
        "Her aralık ayrı bir dosya olur; “8-” son sayfaya kadar gider. Açık belge değiştirilmez.",
    "The document has {count} page(s).": "Belgede {count} sayfa var.",
    "Printing": "Yazdırma",
    "Copying text and images": "Metin ve görselleri kopyalama",
    "Editing and organizing pages": "Düzenleme ve sayfaları yeniden sıralama",
    "Comments and filling in forms": "Yorumlar ve form doldurma",
    "Optional": "İsteğe bağlı",
    "A protected copy is saved as a new file; the open document is not changed. Keep the password in a safe "
    "place: it cannot be recovered.\n\nWithout a permissions password, restrictions cannot be lifted later, "
    "not even by you.":
        "Korumalı kopya yeni bir dosya olarak kaydedilir; açık belge değiştirilmez. Parolayı güvenli bir yerde "
        "saklayın: kurtarılamaz.\n\nİzin parolası belirlemezseniz kısıtlamalar daha sonra kaldırılamaz; siz de "
        "kaldıramazsınız.",
    "The digital signatures in this document will not be valid in the protected copy.":
        "Bu belgedeki dijital imzalar korumalı kopyada geçerli olmayacak.",
    "Password to open:": "Açma parolası:",
    "Repeat password:": "Parolayı tekrarla:",
    "Allow:": "İzin ver:",
    "Permissions password:": "İzin parolası:",
    "The passwords do not match.": "Parolalar eşleşmiyor.",
    "Save merged PDF": "Birleştirilmiş PDF'i kaydet",
    "{base}_merged.pdf": "{base}_birlesik.pdf",
    "Merged PDF saved:\n{path}": "Birleştirilmiş PDF kaydedildi:\n{path}",
    "Save PDF": "PDF'i kaydet",
    "PDF saved:\n{path}": "PDF kaydedildi:\n{path}",
    "{count} PDF file(s) saved in:\n{folder}": "{count} PDF dosyası şu klasöre kaydedildi:\n{folder}",
    "Save protected copy": "Korumalı kopyayı kaydet",
    "{base}_protected.pdf": "{base}_korumali.pdf",
    "Protected copy saved:\n{path}": "Korumalı kopya kaydedildi:\n{path}",
    "Save copy without password": "Parolasız kopyayı kaydet",
    "{base}_unlocked.pdf": "{base}_parolasiz.pdf",
    "A copy without the password and restrictions was saved:\n{path}":
        "Parola ve kısıtlamalar olmadan bir kopya kaydedildi:\n{path}",
    "PDF to repair": "Onarılacak PDF",
    "Save repaired PDF": "Onarılmış PDF'i kaydet",
    "{base}_repaired.pdf": "{base}_onarilmis.pdf",
    "Repaired PDF saved:\n{path}": "Onarılmış PDF kaydedildi:\n{path}",
    "The file's structure was damaged and has been rebuilt.": "Dosyanın yapısı bozulmuştu ve yeniden oluşturuldu.",
    "No structural damage was found; the file was rewritten cleanly.":
        "Yapısal bir bozulma bulunamadı; dosya temiz biçimde yeniden yazıldı.",
    "{count} page(s) recovered.": "{count} sayfa kurtarıldı.",
    "{count} unreadable page(s) could not be recovered and were left out.":
        "Okunamayan {count} sayfa kurtarılamadı ve dışarıda bırakıldı.",
}
