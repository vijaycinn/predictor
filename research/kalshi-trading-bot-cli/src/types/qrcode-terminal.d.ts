declare module 'qrcode-terminal' {
  const qrcode: {
    generate(text: string, options?: { small?: boolean }, cb?: (qr: string) => void): void;
    setErrorLevel(level: string): void;
  };
  export default qrcode;
}
