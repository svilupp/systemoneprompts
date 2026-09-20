import { TypeSafeClient } from "systemoneprompts";
import { walkTaxonomy } from "systemoneprompts/patterns";
import { model } from "./taxonomy.generated.ts";

const tree = {
  "Sporting Goods": {
    Cycling: {
      "Bike Bottles & Cages": "Bottles and cages designed to mount on a bicycle",
    },
  },
  "Home & Kitchen": {
    Drinkware: {
      "Water Bottles": "Everyday bottles for home or office use",
    },
  },
};

const client = new TypeSafeClient();
const paths = await walkTaxonomy(client, {
  state: {
    listing: {
      title: "Insulated bike bottle with cage mounts",
      description: "Fits standard bicycle bottle cages. Leak-proof lid for rides.",
    },
  },
  instructions: {
    question: "Which category best fits this product listing?",
    focus: "Prefer the path whose subtree matches the listing's intended use.",
  },
  tree,
  beamWidth: 2,
  model,
});

console.log(paths);
