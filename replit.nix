{ pkgs }: {
  deps = [
    pkgs.python3
    pkgs.tesseract # Base Tesseract OCR engine
    pkgs.tesseract5 # Tesseract version 5 (often needed for newer versions)
    pkgs.tesseract5.withLangModels # Language models for Tesseract 5
    # ลองใช้ tesseract หรือ tesseract5 ตัวใดตัวหนึ่งก่อน
    # หรือลองใช้ tesseract.withTraineddata, tesseract.withLangPacks ถ้า withLangModels ไม่ได้ผล
  ];
}
