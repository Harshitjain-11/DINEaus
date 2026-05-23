function getCommonImageName(itemName) {
  const name = itemName.toLowerCase();

  if (name.includes("fries")) return "fries.jpg";
  if (name.includes("burger")) return "burger.jpg";
  if (name.includes("pizza")) return "pizza.jpg";
  if (name.includes("noodles")) return "chinese.jpg";
  if (name.includes("biryani")) return "Biryani.jpg";
  if (name.includes("cake")) return "cake.jpg";
  if (name.includes("chole bhature")) return "chole bhature.jpg";
  if (name.includes("dosa")) return "Dosa.jpg";
  if (name.includes("Noodles")) return "noodles.jpg";
  if (name.includes("rolls")) return "Rolls.jpg";
  if (name.includes("momos")) return "Momos.jpg";

  return "default.jpg";
}
module.exports = getCommonImageName;