mod gpu_acceleration;
mod jobs;
mod media;
mod naming;
mod preview;
mod project;
mod resources;
mod tracking;

use jobs::JobRegistry;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    preview::cleanup_preview_root();
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(JobRegistry::default())
        .manage(gpu_acceleration::GpuInstallControl::default())
        .invoke_handler(tauri::generate_handler![
            media::probe_videos,
            naming::suggest_output_path,
            project::save_project,
            project::load_project,
            project::analyze_project,
            resources::resource_status,
            gpu_acceleration::gpu_status,
            gpu_acceleration::install_gpu_component,
            gpu_acceleration::pause_gpu_install,
            jobs::start_export,
            jobs::cancel_job,
            preview::create_preview,
            tracking::track_video,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run 净帧工坊");
}
