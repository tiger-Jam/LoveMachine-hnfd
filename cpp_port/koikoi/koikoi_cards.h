// koikoi_cards.h — カードデータ定義
// Python 実装 (core.py::make_deck) と完全に一致する 48 枚の静的配列を持つ。
// id は 0..47 で、Python 側 Card.id と同一。

#ifndef OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_CARDS_H_
#define OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_CARDS_H_

#include <array>
#include <cstdint>

namespace open_spiel {
namespace koikoi {

inline constexpr int kNumCards = 48;

enum class CardType : uint8_t {
  kHikari = 0,   // 光
  kTane = 1,     // 種
  kTanzaku = 2,  // 短冊
  kKasu = 3,     // カス
};

enum class TanzakuType : uint8_t {
  kNone = 0,     // non-tanzaku card
  kAkatan = 1,   // 赤短 (松/梅/桜)
  kAotan = 2,    // 青短 (牡丹/菊/紅葉)
  kMuji = 3,     // 無地 (藤/菖蒲/萩/柳)
};

struct CardInfo {
  uint8_t id;                 // 0..47
  uint8_t month;              // 1..12
  const char* name;           // 例: "松に鶴"
  CardType type;
  TanzakuType tanzaku;        // kNone if not tanzaku
};

// core.py::make_deck() の add() 順序を完全再現。
// id は配列インデックスと一致する。
inline constexpr std::array<CardInfo, kNumCards> kDeck = {{
    // 1 月 松
    { 0,  1, "松に鶴",       CardType::kHikari,  TanzakuType::kNone},
    { 1,  1, "松に赤短",      CardType::kTanzaku, TanzakuType::kAkatan},
    { 2,  1, "松のカス①",    CardType::kKasu,    TanzakuType::kNone},
    { 3,  1, "松のカス②",    CardType::kKasu,    TanzakuType::kNone},
    // 2 月 梅
    { 4,  2, "梅に鶯",       CardType::kTane,    TanzakuType::kNone},
    { 5,  2, "梅に赤短",      CardType::kTanzaku, TanzakuType::kAkatan},
    { 6,  2, "梅のカス①",    CardType::kKasu,    TanzakuType::kNone},
    { 7,  2, "梅のカス②",    CardType::kKasu,    TanzakuType::kNone},
    // 3 月 桜
    { 8,  3, "桜に幕",       CardType::kHikari,  TanzakuType::kNone},
    { 9,  3, "桜に赤短",      CardType::kTanzaku, TanzakuType::kAkatan},
    {10,  3, "桜のカス①",    CardType::kKasu,    TanzakuType::kNone},
    {11,  3, "桜のカス②",    CardType::kKasu,    TanzakuType::kNone},
    // 4 月 藤
    {12,  4, "藤に不如帰",    CardType::kTane,    TanzakuType::kNone},
    {13,  4, "藤に短冊",      CardType::kTanzaku, TanzakuType::kMuji},
    {14,  4, "藤のカス①",    CardType::kKasu,    TanzakuType::kNone},
    {15,  4, "藤のカス②",    CardType::kKasu,    TanzakuType::kNone},
    // 5 月 菖蒲
    {16,  5, "菖蒲に八橋",    CardType::kTane,    TanzakuType::kNone},
    {17,  5, "菖蒲に短冊",    CardType::kTanzaku, TanzakuType::kMuji},
    {18,  5, "菖蒲のカス①",  CardType::kKasu,    TanzakuType::kNone},
    {19,  5, "菖蒲のカス②",  CardType::kKasu,    TanzakuType::kNone},
    // 6 月 牡丹
    {20,  6, "牡丹に蝶",      CardType::kTane,    TanzakuType::kNone},
    {21,  6, "牡丹に青短",    CardType::kTanzaku, TanzakuType::kAotan},
    {22,  6, "牡丹のカス①",  CardType::kKasu,    TanzakuType::kNone},
    {23,  6, "牡丹のカス②",  CardType::kKasu,    TanzakuType::kNone},
    // 7 月 萩
    {24,  7, "萩に猪",       CardType::kTane,    TanzakuType::kNone},
    {25,  7, "萩に短冊",      CardType::kTanzaku, TanzakuType::kMuji},
    {26,  7, "萩のカス①",    CardType::kKasu,    TanzakuType::kNone},
    {27,  7, "萩のカス②",    CardType::kKasu,    TanzakuType::kNone},
    // 8 月 芒
    {28,  8, "芒に月",       CardType::kHikari,  TanzakuType::kNone},
    {29,  8, "芒に雁",       CardType::kTane,    TanzakuType::kNone},
    {30,  8, "芒のカス①",    CardType::kKasu,    TanzakuType::kNone},
    {31,  8, "芒のカス②",    CardType::kKasu,    TanzakuType::kNone},
    // 9 月 菊
    {32,  9, "菊に盃",       CardType::kTane,    TanzakuType::kNone},
    {33,  9, "菊に青短",      CardType::kTanzaku, TanzakuType::kAotan},
    {34,  9, "菊のカス①",    CardType::kKasu,    TanzakuType::kNone},
    {35,  9, "菊のカス②",    CardType::kKasu,    TanzakuType::kNone},
    // 10 月 紅葉
    {36, 10, "紅葉に鹿",      CardType::kTane,    TanzakuType::kNone},
    {37, 10, "紅葉に青短",    CardType::kTanzaku, TanzakuType::kAotan},
    {38, 10, "紅葉のカス①",  CardType::kKasu,    TanzakuType::kNone},
    {39, 10, "紅葉のカス②",  CardType::kKasu,    TanzakuType::kNone},
    // 11 月 柳
    {40, 11, "柳に小野道風",  CardType::kHikari,  TanzakuType::kNone},
    {41, 11, "柳に燕",       CardType::kTane,    TanzakuType::kNone},
    {42, 11, "柳に短冊",      CardType::kTanzaku, TanzakuType::kMuji},
    {43, 11, "柳のカス",      CardType::kKasu,    TanzakuType::kNone},
    // 12 月 桐
    {44, 12, "桐に鳳凰",      CardType::kHikari,  TanzakuType::kNone},
    {45, 12, "桐のカス①",    CardType::kKasu,    TanzakuType::kNone},
    {46, 12, "桐のカス②",    CardType::kKasu,    TanzakuType::kNone},
    {47, 12, "桐のカス③",    CardType::kKasu,    TanzakuType::kNone},
}};

inline constexpr const CardInfo& Card(int id) { return kDeck[id]; }

// 特定札の id 定数 (core.py の _find 相当)。役判定で使う。
inline constexpr int kIdMatsuTsuru     = 0;
inline constexpr int kIdSakuraMaku     = 8;
inline constexpr int kIdSusukiTsuki    = 28;
inline constexpr int kIdKikuSakazuki   = 32;
inline constexpr int kIdHagiIno        = 24;
inline constexpr int kIdMomijiShika    = 36;
inline constexpr int kIdBotanChou      = 20;
inline constexpr int kIdYanagiMichikaze = 40;
inline constexpr int kIdKiriHoou       = 44;

// Bitmask 表現 (48bit) — 役判定を高速化するため取り札集合を uint64_t で持つ。
using CardMask = uint64_t;
inline constexpr CardMask kBit(int id) { return CardMask{1} << id; }

// 型別マスク (コンパイル時定数)
inline constexpr CardMask ComputeTypeMask(CardType t) {
  CardMask m = 0;
  for (int i = 0; i < kNumCards; ++i) {
    if (kDeck[i].type == t) m |= kBit(i);
  }
  return m;
}
inline constexpr CardMask ComputeTanzakuMask(TanzakuType t) {
  CardMask m = 0;
  for (int i = 0; i < kNumCards; ++i) {
    if (kDeck[i].tanzaku == t) m |= kBit(i);
  }
  return m;
}
inline constexpr CardMask ComputeMonthMask(int month) {
  CardMask m = 0;
  for (int i = 0; i < kNumCards; ++i) {
    if (kDeck[i].month == month) m |= kBit(i);
  }
  return m;
}

inline constexpr CardMask kHikariMask  = ComputeTypeMask(CardType::kHikari);
inline constexpr CardMask kTaneMask    = ComputeTypeMask(CardType::kTane);
inline constexpr CardMask kTanzakuMask = ComputeTypeMask(CardType::kTanzaku);
inline constexpr CardMask kKasuMask    = ComputeTypeMask(CardType::kKasu);
inline constexpr CardMask kAkatanMask  = ComputeTanzakuMask(TanzakuType::kAkatan);
inline constexpr CardMask kAotanMask   = ComputeTanzakuMask(TanzakuType::kAotan);

// 猪鹿蝶 = 萩に猪 + 紅葉に鹿 + 牡丹に蝶
inline constexpr CardMask kInoshikachoMask =
    kBit(kIdHagiIno) | kBit(kIdMomijiShika) | kBit(kIdBotanChou);
// 花見で一杯 = 桜に幕 + 菊に盃
inline constexpr CardMask kHanamiMask =
    kBit(kIdSakuraMaku) | kBit(kIdKikuSakazuki);
// 月見で一杯 = 芒に月 + 菊に盃
inline constexpr CardMask kTsukimiMask =
    kBit(kIdSusukiTsuki) | kBit(kIdKikuSakazuki);
// 柳光 (雨)
inline constexpr CardMask kYanagiHikariBit = kBit(kIdYanagiMichikaze);

// popcount (C++20 std::popcount 代替、古いコンパイラ対応)
inline constexpr int PopCount(CardMask m) {
  int n = 0;
  while (m) { n += (m & 1); m >>= 1; }
  return n;
}

}  // namespace koikoi
}  // namespace open_spiel

#endif  // OPEN_SPIEL_GAMES_KOIKOI_KOIKOI_CARDS_H_
