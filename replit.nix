{ pkgs }: {
  deps = [
    pkgs.python3Full
    pkgs.tesseract # ติดตั้ง Tesseract OCR engine
    pkgs.tesseract.withLangModels # ติดตั้งภาษา (รวมถึง eng, tha)
  ];
}
