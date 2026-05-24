import type { Hexagram } from "./types";

const trigramNameMap: Record<string, string> = {
  Qian: "\u4e7e",
  Dui: "\u5151",
  Li: "\u79bb",
  Zhen: "\u9707",
  Xun: "\u5dfd",
  Kan: "\u574e",
  Gen: "\u826e",
  Kun: "\u5764",
};

const elementMap: Record<string, string> = {
  metal: "\u91d1",
  wood: "\u6728",
  water: "\u6c34",
  fire: "\u706b",
  earth: "\u571f",
};

const hexagramNameMap: Record<string, string> = {
  "111111": "\u4e7e\u4e3a\u5929",
  "111110": "\u5929\u6cfd\u5c65",
  "111101": "\u5929\u706b\u540c\u4eba",
  "111100": "\u5929\u96f7\u65e0\u5984",
  "111011": "\u5929\u98ce\u59e4",
  "111010": "\u5929\u6c34\u8bbc",
  "111001": "\u5929\u5c71\u9041",
  "111000": "\u5929\u5730\u5426",
  "110111": "\u6cfd\u5929\u592c",
  "110110": "\u5151\u4e3a\u6cfd",
  "110101": "\u6cfd\u706b\u9769",
  "110100": "\u6cfd\u96f7\u968f",
  "110011": "\u6cfd\u98ce\u5927\u8fc7",
  "110010": "\u6cfd\u6c34\u56f0",
  "110001": "\u6cfd\u5c71\u54b8",
  "110000": "\u6cfd\u5730\u8403",
  "101111": "\u706b\u5929\u5927\u6709",
  "101110": "\u706b\u6cfd\u777d",
  "101101": "\u79bb\u4e3a\u706b",
  "101100": "\u706b\u96f7\u565c\u55d1",
  "101011": "\u706b\u98ce\u9f0e",
  "101010": "\u706b\u6c34\u672a\u6d4e",
  "101001": "\u706b\u5c71\u65c5",
  "101000": "\u706b\u5730\u664b",
  "100111": "\u96f7\u5929\u5927\u58ee",
  "100110": "\u96f7\u6cfd\u5f52\u59b9",
  "100101": "\u96f7\u706b\u4e30",
  "100100": "\u9707\u4e3a\u96f7",
  "100011": "\u96f7\u98ce\u6052",
  "100010": "\u96f7\u6c34\u89e3",
  "100001": "\u96f7\u5c71\u5c0f\u8fc7",
  "100000": "\u96f7\u5730\u8c6b",
  "011111": "\u98ce\u5929\u5c0f\u755c",
  "011110": "\u98ce\u6cfd\u4e2d\u5b5a",
  "011101": "\u98ce\u706b\u5bb6\u4eba",
  "011100": "\u98ce\u96f7\u76ca",
  "011011": "\u5dfd\u4e3a\u98ce",
  "011010": "\u98ce\u6c34\u6da3",
  "011001": "\u98ce\u5c71\u6e10",
  "011000": "\u98ce\u5730\u89c2",
  "010111": "\u6c34\u5929\u9700",
  "010110": "\u6c34\u6cfd\u8282",
  "010101": "\u6c34\u706b\u65e2\u6d4e",
  "010100": "\u6c34\u96f7\u5c6f",
  "010011": "\u6c34\u98ce\u4e95",
  "010010": "\u574e\u4e3a\u6c34",
  "010001": "\u6c34\u5c71\u8e47",
  "010000": "\u6c34\u5730\u6bd4",
  "001111": "\u5c71\u5929\u5927\u755c",
  "001110": "\u5c71\u6cfd\u635f",
  "001101": "\u5c71\u706b\u8d32",
  "001100": "\u5c71\u96f7\u9890",
  "001011": "\u5c71\u98ce\u86ca",
  "001010": "\u5c71\u6c34\u8499",
  "001001": "\u826e\u4e3a\u5c71",
  "001000": "\u5c71\u5730\u5265",
  "000111": "\u5730\u5929\u6cf0",
  "000110": "\u5730\u6cfd\u4e34",
  "000101": "\u5730\u706b\u660e\u5937",
  "000100": "\u5730\u96f7\u590d",
  "000011": "\u5730\u98ce\u5347",
  "000010": "\u5730\u6c34\u5e08",
  "000001": "\u5730\u5c71\u8c26",
  "000000": "\u5764\u4e3a\u5730",
};

export function displayHexagramName(hexagram: Hexagram) {
  return hexagramNameMap[hexagram.code] ?? hexagram.name;
}

export function displayTrigramName(name: string) {
  return trigramNameMap[name] ?? name;
}

export function displayElementName(name: string) {
  return elementMap[name] ?? name;
}
