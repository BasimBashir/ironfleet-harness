import { createRoot } from "react-dom/client";
import "../../design/system/tokens.css";
import "../../design/system/components.css";
import "./app.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(<App />);
