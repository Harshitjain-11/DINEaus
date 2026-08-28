// utils/getCommonImageName.js
// Maps a menu item name to an individual dish image filename.
// All files are .png and are served from the Express static root (public/).
// Callers should prepend "/" to construct the URL: "/" + getCommonImageName(name)
// Returns "default.png" when no match is found.
function getCommonImageName(itemName) {
  const name = itemName.toLowerCase();

  if (name.includes("french fries") || name.includes("fries")) return "French Fries.png";
  if (name.includes("burger"))        return "Burger.png";
  if (name.includes("pizza"))         return "Pizza.png";
  if (name.includes("chinese")) return "Chinese.png";
  if (name.includes("chowmein") || name.includes("chow mein") || name.includes("noodles")) return "Noodles.png";
  if (name.includes("biryani"))       return "Biryani.png";
  if (name.includes("cake"))          return "Cake.png";
  if (name.includes("chole") || name.includes("bhature") || name.includes("bhatura") || name.includes("bratre")) return "Chole Bhature.png";
  if (name.includes("dosa"))          return "Dosa.png";
  if (name.includes("rolls"))         return "Rolls.png";
  if (name.includes("momos"))         return "Momos.png";
  if (name.includes("samosa"))        return "Samosa.png";
  if (name.includes("idli") || name.includes("itli")) return "Itli.png";
  if (name.includes("pavbhaji") || name.includes("pav bhaji") || name.includes("paw bhaji")) return "Paw Bhaji.png";
  if (name.includes("paneer tikka")) return "Paneer Tikka.png";
  if (name.includes("north indian") || name.includes("thali")) return "NorthIndian.png";
  if (name.includes("dhokla"))        return "Dhokla.png";
  if (name.includes("sandwich") || name.includes("sandwitch")) return "SandWitch.png";
  if (name.includes("coffee"))        return "Coffee.png";
  if (name.includes("platters") || name.includes("platter")) return "Platters.png";

  // Safe fallback: use Dosa.png as a neutral food image
  return "Dosa.png";
}

module.exports = getCommonImageName;