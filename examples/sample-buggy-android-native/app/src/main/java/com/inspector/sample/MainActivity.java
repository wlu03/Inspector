package com.inspector.sample;

import android.app.Activity;
import android.os.Bundle;
import android.util.Log;
import android.widget.Button;
import android.widget.EditText;
import android.widget.TextView;

/**
 * The canonical planted bug, native edition: the Save button is supposed to show a
 * "Saved" confirmation, but it throws a NullPointerException first — so the UI never
 * updates. Inspector should catch it via the logcat tap (the Log.e signature + the
 * uncaught exception) and verify-after-act (the toast text never changes).
 */
public class MainActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        Button save = findViewById(R.id.save);
        final TextView toast = findViewById(R.id.toast);
        final EditText name = findViewById(R.id.name);

        save.setOnClickListener(v -> {
            Log.e("Inspector", "query not invalidated after save");
            String result = null;
            toast.setText(result.trim());  // BUG: NullPointerException — crashes here
            toast.setText("Saved");        // unreachable
        });
    }
}
