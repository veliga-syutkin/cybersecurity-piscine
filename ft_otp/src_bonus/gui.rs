use std::time::{Duration, SystemTime, UNIX_EPOCH};

use eframe::egui;
use qrcode::{Color, QrCode};

use crate::errors::Error;
use crate::options::Passphrase;
use crate::{qr, storage, totp};

const WINDOW_TITLE: &str = "ft_otp";
const WINDOW_SIZE: [f32; 2] = [380.0, 600.0]; // width, height in pixels
const CODE_FONT_SIZE: f32 = 56.0;
const FIELD_WIDTH: f32 = 200.0; // text fields: room left for the Load button
const QR_MODULE_SIZE: f32 = 6.0; // pixels per square of the QR code
const QR_QUIET_ZONE: f32 = 4.0; // white margin a scanner needs (ISO 18004)
const REFRESH_EVERY: Duration = Duration::from_millis(250); // countdown

/*
  Everything the window shows or remembers between two frames.
  egui is an "immediate mode" GUI: ui () redraws the WHOLE window at each
  frame from these fields, there is no widget to keep in sync.
	path              the "Key file" text field
	passphrase        the hidden field, shown if the file needs it
	needs_passphrase  what the mode byte of the file said (see Load)
	key               the decrypted key, once loaded: the code is
	                  computed from it at each frame
	qr                the QR code, while "Show QR code" is on
	status            the last message (error or info), and if error
*/
struct App {
	path: String,
	passphrase: String,
	needs_passphrase: bool,
	key: Option<Vec<u8>>,
	qr: Option<QrCode>,
	status: String,
	status_is_error: bool,
}

impl App {
	/* Opens on PATH (or ft_otp.key), and loads it at once if it needs no
	passphrase: with a machine-id key file, the code shows right away.
	*/
	fn new(path: Option<&str>) -> Self {
		let mut app = App {
			path: path.unwrap_or(storage::KEY_FILE).to_string(),
			passphrase: String::new(),
			needs_passphrase: false,
			key: None,
			qr: None,
			status: String::new(),
			status_is_error: false,
		};
		app.load();
		app
	}

	fn set_status(&mut self, message: String, is_error: bool) {
		self.status = message;
		self.status_is_error = is_error;
	}

	/* The "Load" button (or Enter in a field), like -k:
		1) read the mode byte: does this file need a passphrase?
		2) if yes and none is typed yet: show the field, wait
		3) decrypt (storage::load_key), forget the typed passphrase
	The old key and QR code are dropped first: a failed load shows nothing.
	*/
	fn load(&mut self) {
		self.key = None;
		self.qr = None;
		self.needs_passphrase = match storage::needs_passphrase(&self.path) {
			Ok(needed) => needed,
			Err(Error::Fatal(e)) | Err(Error::Usage(e)) => return self.set_status(e, true),
		};
		if self.needs_passphrase && self.passphrase.is_empty() {
			return self.set_status("This key file needs its passphrase.".to_string(), false);
		}
		let source = match self.needs_passphrase {
			true => Passphrase::Given(std::mem::take(&mut self.passphrase)),
			false => Passphrase::Absent,
		};
		match storage::load_key(&self.path, &source) {
			Ok(key) => {
				self.key = Some(key);
				self.set_status(format!("{} loaded.", self.path), false);
			}
			Err(Error::Fatal(e)) | Err(Error::Usage(e)) => self.set_status(e, true),
		}
	}

	/* Key file field, passphrase field if needed, Load button.
	Enter in a field = Load.
	*/
	fn key_file_ui(&mut self, ui: &mut egui::Ui) {
		let mut load = false;

		ui.horizontal(|ui| {
			ui.label("Key file:");
			let field = ui.add(egui::TextEdit::singleline(&mut self.path).desired_width(FIELD_WIDTH));
			load |= field.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
			load |= ui.button("Load").clicked();
		});
		if self.needs_passphrase && self.key.is_none() {
			ui.horizontal(|ui| {
				ui.label("Passphrase:");
				let field = ui.add(
					egui::TextEdit::singleline(&mut self.passphrase)
						.password(true)
						.desired_width(FIELD_WIDTH),
				);
				load |= field.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
			});
		}
		if load {
			self.load();
		}
	}

	/* The code of now, in big, the seconds before the next one, and the
	Copy / Show QR code buttons. Everything is recomputed at each frame
	(an HMAC is nothing for a CPU), so the code changes by itself.
	*/
	fn code_ui(&mut self, ui: &mut egui::Ui, key: &[u8]) {
		let code = match totp::totp_now(key) {
			Ok(code) => code,
			Err(Error::Fatal(e)) | Err(Error::Usage(e)) => return self.set_status(e, true),
		};
		let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
		let left = totp::TIME_STEP - now.as_secs() % totp::TIME_STEP;

		ui.label(egui::RichText::new(&code).size(CODE_FONT_SIZE).monospace().strong());
		ui.add(
			egui::ProgressBar::new(left as f32 / totp::TIME_STEP as f32)
				.text(format!("{} s", left)),
		);
		ui.horizontal(|ui| {
			if ui.button("Copy").clicked() {
				ui.ctx().copy_text(code.clone());
				self.set_status("Code copied.".to_string(), false);
			}
			let label = if self.qr.is_some() { "Hide QR code" } else { "Show QR code" };
			if ui.button(label).clicked() {
				self.toggle_qr(key);
			}
		});
	}

	fn toggle_qr(&mut self, key: &[u8]) {
		if self.qr.take().is_some() {
			return;
		}
		match qr::qr_code(key) {
			Ok(code) => self.qr = Some(code),
			Err(Error::Fatal(e)) | Err(Error::Usage(e)) => self.set_status(e, true),
		}
	}
}

/* Draws CODE as black squares on a white square, with its quiet zone:
no image crate, egui paints rectangles.
*/
fn draw_qr(ui: &mut egui::Ui, code: &QrCode) {
	let width = code.width();
	let side = (width as f32 + 2.0 * QR_QUIET_ZONE) * QR_MODULE_SIZE;
	let (response, painter) = ui.allocate_painter(egui::vec2(side, side), egui::Sense::hover());
	let origin = response.rect.min + egui::vec2(QR_QUIET_ZONE, QR_QUIET_ZONE) * QR_MODULE_SIZE;

	painter.rect_filled(response.rect, 0.0, egui::Color32::WHITE);
	for (i, color) in code.to_colors().iter().enumerate() {
		if *color == Color::Dark {
			let (x, y) = ((i % width) as f32, (i / width) as f32);
			let corner = origin + egui::vec2(x, y) * QR_MODULE_SIZE;
			let square = egui::Rect::from_min_size(corner, egui::vec2(QR_MODULE_SIZE, QR_MODULE_SIZE));
			painter.rect_filled(square, 0.0, egui::Color32::BLACK);
		}
	}
}

impl eframe::App for App {
	/* Called at each frame: redraws the whole window from App's fields,
	then asks for a new frame in REFRESH_EVERY, for the countdown.
	*/
	fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
		egui::CentralPanel::default_margins().show(ui, |ui| {
			ui.vertical_centered(|ui| {
				ui.heading(WINDOW_TITLE);
				ui.separator();
				self.key_file_ui(ui);
				if let Some(key) = self.key.clone() {
					ui.separator();
					self.code_ui(ui, &key);
				}
				if let Some(code) = &self.qr {
					draw_qr(ui, code);
				}
				if !self.status.is_empty() {
					let color = if self.status_is_error { egui::Color32::RED } else { ui.visuals().text_color() };
					ui.colored_label(color, &self.status);
				}
			});
		});
		ui.ctx().request_repaint_after(REFRESH_EVERY);
	}
}

/* --gui [PATH]: opens the window, returns when it is closed.
Fails if no window can be opened (no display...).
*/
pub fn run_gui(path: Option<&str>) -> Result<(), Error> {
	let options = eframe::NativeOptions {
		viewport: egui::ViewportBuilder::default()
			.with_title(WINDOW_TITLE)
			.with_inner_size(WINDOW_SIZE),
		..Default::default()
	};
	let app = App::new(path);

	eframe::run_native(WINDOW_TITLE, options, Box::new(|_| Ok(Box::new(app))))
		.map_err(|e| Error::Fatal(format!("cannot open the window: {}", e)))
}
