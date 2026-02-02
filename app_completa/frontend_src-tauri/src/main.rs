// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use tauri::Manager;
use tauri::api::process::{Command, CommandEvent};

struct BackendConfig {
    port: u16,
}

#[tauri::command]
fn get_backend_port(state: tauri::State<BackendConfig>) -> u16 {
    state.port
}

fn main() {
    // Find a free port
    let listener = TcpListener::bind("127.0.0.1:0").expect("Failed to bind to free port");
    let port = listener.local_addr().expect("Failed to get local address").port();
    drop(listener); // Close the listener so the backend can bind to it

    println!("[Rust] Selected dynamic backend port: {}", port);

    tauri::Builder::default()
        .manage(BackendConfig { port })
        .setup(move |app| {
            let window = app.get_window("main").unwrap();
            let app_handle = app.handle();
            let port_arg = port.to_string();
            
            // Spawn the sidecar (Python backend) in a monitoring loop
            tauri::async_runtime::spawn(async move {
                loop {
                    println!("[Rust] Spawning backend sidecar on port {}...", port_arg);
                    let _ = app_handle.emit_all("backend-stdout", format!("[Rust] Spawning backend sidecar on port {}...", port_arg));

                    let cmd = Command::new_sidecar("conciliacion-backend")
                        .expect("failed to create `conciliacion-backend` binary command")
                        .args(&["--port", &port_arg]);
                        
                    match cmd.spawn() {
                        Ok((mut rx, _child)) => {
                            println!("[Rust] Backend started successfully");
                            let _ = app_handle.emit_all("backend-stdout", "[Rust] Backend started successfully");
                            
                            // Process output until the process exits
                            while let Some(event) = rx.recv().await {
                                match event {
                                    CommandEvent::Stdout(line) => {
                                        println!("[PY] {}", line);
                                        let _ = app_handle.emit_all("backend-stdout", line);
                                    }
                                    CommandEvent::Stderr(line) => {
                                        eprintln!("[PY ERR] {}", line);
                                        let _ = app_handle.emit_all("backend-stderr", line);
                                    }
                                    _ => {}
                                }
                            }
                            
                            println!("[Rust] Backend process exited unexpectedly. Restarting in 2 seconds...");
                            let _ = app_handle.emit_all("backend-stderr", "[Rust] Backend process exited unexpectedly. Restarting in 2 seconds...");
                        }
                        Err(e) => {
                            eprintln!("[Rust] Failed to spawn sidecar: {}", e);
                             let msg = format!("[Rust] Failed to spawn sidecar: {}", e);
                            let _ = app_handle.emit_all("backend-stderr", msg);
                            println!("[Rust] Retrying in 2 seconds...");
                        }
                    }
                    
                    // Wait before restarting to prevent crash loops
                    std::thread::sleep(std::time::Duration::from_secs(2));
                }
            });

            // Apply macOS vibrancy effect for native look (Sidebar style)
            #[cfg(target_os = "macos")]
            {
                use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};
                apply_vibrancy(
                    &window,
                    NSVisualEffectMaterial::Sidebar,
                    None,
                    None
                ).ok(); // Ignore errors if it fails
                
                 window.show().unwrap();
            }

            Ok(())
        })
        .on_window_event(|event| match event.event() {
            tauri::WindowEvent::CloseRequested { .. } => {
                std::process::exit(0);
            }
            _ => {}
        })
        .invoke_handler(tauri::generate_handler![
            get_app_data_dir,
            open_folder_in_finder,
            show_notification,
            get_backend_port
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// Get the application data directory
#[tauri::command]
fn get_app_data_dir(app_handle: tauri::AppHandle) -> Result<String, String> {
    app_handle
        .path_resolver()
        .app_data_dir()
        .map(|path| path.to_string_lossy().to_string())
        .ok_or_else(|| "Could not get app data directory".to_string())
}

/// Open a folder in Finder (macOS)
#[tauri::command]
fn open_folder_in_finder(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        std::process::Command::new("open")
        .arg(&path)
        .spawn()
        .map_err(|e| e.to_string())?;
    }
    
    // For other platforms we just ignore or log
    #[cfg(not(target_os = "macos"))]
    { let _ = path; }

    Ok(())
}

/// Show a native notification
#[tauri::command]
fn show_notification(title: String, body: String) -> Result<(), String> {
    tauri::api::notification::Notification::new("com.conciliacion.financiera")
        .title(&title)
        .body(&body)
        .show()
        .map_err(|e| e.to_string())
}
