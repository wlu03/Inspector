import { useState } from "react";
import { Button, Text, TextInput, View } from "react-native";

// Same bug as the other samples: Save should show a "Saved" confirmation but
// throws a TypeError first (logged to logcat / Metro), so nothing updates.
export default function App() {
  const [name, setName] = useState("");
  const [toast, setToast] = useState("");

  const onSave = () => {
    console.error("query not invalidated after save");
    const result = undefined;
    result.show(); // BUG: TypeError
    setToast("Saved"); // unreachable
  };

  return (
    <View style={{ flex: 1, justifyContent: "center", padding: 24 }}>
      <Text style={{ fontSize: 28, fontWeight: "bold" }}>Settings</Text>
      <TextInput
        placeholder="Your name"
        value={name}
        onChangeText={setName}
        style={{ borderWidth: 1, padding: 8, marginVertical: 12 }}
      />
      <Button title="Save" onPress={onSave} />
      <Text style={{ color: "green", marginTop: 12 }}>{toast}</Text>
    </View>
  );
}
