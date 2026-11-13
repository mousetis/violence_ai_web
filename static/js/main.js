// Chuyen doi che do sang / toi, luu lai trong trinh duyet cho lan sau
function applyThemeButtonLabel() {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  var isLight = document.documentElement.getAttribute("data-theme") === "light";
  btn.textContent = isLight ? "🌙  Chế độ tối" : "☀️  Chế độ sáng";
}
function toggleTheme() {
  var isLight = document.documentElement.getAttribute("data-theme") === "light";
  var next = isLight ? "dark" : "light";
  if (next === "dark") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", next);
  }
  try { localStorage.setItem("va_theme", next); } catch (e) {}
  applyThemeButtonLabel();
}
window.toggleTheme = toggleTheme;
document.addEventListener("DOMContentLoaded", applyThemeButtonLabel);

// Chon nhieu (checkbox) de xoa hang loat - dung chung cho camera va su kien
function toggleAllChecks(cls, checked) {
  document.querySelectorAll("." + cls).forEach(function (cb) { cb.checked = checked; });
}
function confirmBulkDelete(label, cls) {
  var checked = document.querySelectorAll("." + cls + ":checked");
  if (checked.length === 0) {
    alert("Bạn chưa chọn " + label + " nào.");
    return false;
  }
  return confirm("Xoá vĩnh viễn " + checked.length + " " + label + " đã chọn? Không thể hoàn tác.");
}
window.toggleAllChecks = toggleAllChecks;
window.confirmBulkDelete = confirmBulkDelete;

// Tu dong an thong bao flash sau vai giay
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity 0.4s ease";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 400);
    }, 5000);
  });
});

// Bat/tat khung sua camera (trang Camera)
function toggleCameraEdit(cameraId) {
  var panel = document.getElementById("edit-" + cameraId);
  if (panel) panel.classList.toggle("open");
}
window.toggleCameraEdit = toggleCameraEdit;

// Chuyen doi hien thi truong "Webcam" / "RTSP" theo lua chon nguon camera.
// Dung cho ca form them camera va tung form sua camera (tim trong pham vi
// <form> gan nhat thay vi dua vao id co dinh, de dung duoc voi nhieu form
// tren cung 1 trang).
function updateCameraSourceUI(radio) {
  var form = radio.closest("form");
  if (!form) return;
  var isWebcam = radio.value === "webcam";
  var webcamGroup = form.querySelector(".webcam-fields");
  var rtspGroup = form.querySelector(".rtsp-fields");
  if (webcamGroup) webcamGroup.style.display = isWebcam ? "" : "none";
  if (rtspGroup) rtspGroup.style.display = isWebcam ? "none" : "";
}
window.updateCameraSourceUI = updateCameraSourceUI;

document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll('form').forEach(function (form) {
    var checked = form.querySelector('input[name="source_type"]:checked');
    if (checked) updateCameraSourceUI(checked);
  });
});

// Chuyen doi hien thi giua "Web app tu ket noi" (pull) va "Camera AI tu gui
// du lieu ve" (push, Edge AI) - o che do push thi khong can chon nguon
// webcam/RTSP/do nhay nua vi viec quay + phat hien da do thiet bi AI rieng
// dam nhiem, web app chi con nhan ket qua qua API.
function updateCameraInputModeUI(radio) {
  var form = radio.closest("form");
  if (!form) return;
  var isPush = radio.value === "push";
  form.querySelectorAll(".pull-only-fields").forEach(function (el) {
    el.style.display = isPush ? "none" : "";
  });
  form.querySelectorAll(".push-only-fields").forEach(function (el) {
    el.style.display = isPush ? "" : "none";
  });
}
window.updateCameraInputModeUI = updateCameraInputModeUI;

document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll('form').forEach(function (form) {
    var checked = form.querySelector('input[name="input_mode"]:checked');
    if (checked) updateCameraInputModeUI(checked);
  });
});

// Hop thoai chon "Chuyen vao thung rac" / "Xoa vinh vien" - dung chung cho
// moi nut xoa (camera, su kien, dan don hang loat). targetFormId la id cua
// 1 <form> co san tren trang (co the la form rieng cho 1 muc, hoac form
// dan don co checkbox) - modal chi doi "action" cua form do roi submit,
// khong tao form moi, de khong pha vo cac checkbox da gan qua thuoc tinh
// form="...".
var _deleteChoiceCtx = null;
function openDeleteChoice(label, softUrl, hardUrl, targetFormId, checkboxClass) {
  if (checkboxClass) {
    var checked = document.querySelectorAll("." + checkboxClass + ":checked");
    if (checked.length === 0) {
      alert("Bạn chưa chọn " + label + " nào.");
      return;
    }
  }
  _deleteChoiceCtx = { softUrl: softUrl, hardUrl: hardUrl, targetFormId: targetFormId };
  var labelEl = document.getElementById("delete-choice-label");
  if (labelEl) labelEl.textContent = label;
  var modal = document.getElementById("delete-choice-modal");
  if (modal) modal.classList.add("open");
}
function closeDeleteChoice() {
  var modal = document.getElementById("delete-choice-modal");
  if (modal) modal.classList.remove("open");
  _deleteChoiceCtx = null;
}
function confirmDeleteChoice(kind) {
  if (!_deleteChoiceCtx) return;
  if (kind === "hard" && !confirm("Xoá VĨNH VIỄN sẽ không thể hoàn tác. Tiếp tục?")) return;
  var form = document.getElementById(_deleteChoiceCtx.targetFormId);
  if (!form) return;
  form.setAttribute("action", kind === "soft" ? _deleteChoiceCtx.softUrl : _deleteChoiceCtx.hardUrl);
  closeDeleteChoice();
  form.submit();
}
window.openDeleteChoice = openDeleteChoice;
window.closeDeleteChoice = closeDeleteChoice;
window.confirmDeleteChoice = confirmDeleteChoice;

// Dung trong trang Thung rac: khoi phuc/hoac xoa vinh vien hang loat cac
// muc da tick chon - khong can hop thoai 3 lua chon vi o day chi co dung
// 2 hanh dong ro rang (khong phai "xoa thuong vs xoa han" nua).
function submitBulkChecked(formId, checkboxClass, label) {
  var checked = document.querySelectorAll("." + checkboxClass + ":checked");
  if (checked.length === 0) {
    alert("Bạn chưa chọn " + label + " nào.");
    return;
  }
  document.getElementById(formId).submit();
}
function submitBulkPermanent(formId, checkboxClass, permanentUrl, label) {
  var checked = document.querySelectorAll("." + checkboxClass + ":checked");
  if (checked.length === 0) {
    alert("Bạn chưa chọn " + label + " nào.");
    return;
  }
  if (!confirm("Xoá VĨNH VIỄN " + checked.length + " " + label + " đã chọn? Không thể hoàn tác.")) return;
  var form = document.getElementById(formId);
  form.setAttribute("action", permanentUrl);
  form.submit();
}
window.submitBulkChecked = submitBulkChecked;
window.submitBulkPermanent = submitBulkPermanent;

// Cac ham "...FromButton" ben duoi doc URL/nhan tu thuoc tinh data-* cua
// chinh nut bam thay vi nhan tham so truc tiep trong onclick="..." - ly do:
// url_for(...) cua Jinja render ra URL that (khong con dau ngoac don) o
// thuoc tinh data-*, nen khong bao gio bi long dau nhay voi chuoi JavaScript
// trong onclick nua (tranh loi cu phap va sai lech dau ngoac).
function openDeleteChoiceFromButton(btn) {
  openDeleteChoice(
    btn.getAttribute("data-label"),
    btn.getAttribute("data-soft-url"),
    btn.getAttribute("data-hard-url"),
    btn.getAttribute("data-target-form"),
    btn.getAttribute("data-checkbox-class") || null
  );
}
function submitBulkPermanentFromButton(btn) {
  submitBulkPermanent(
    btn.getAttribute("data-form-id"),
    btn.getAttribute("data-checkbox-class"),
    btn.getAttribute("data-permanent-url"),
    btn.getAttribute("data-label")
  );
}
window.openDeleteChoiceFromButton = openDeleteChoiceFromButton;
window.submitBulkPermanentFromButton = submitBulkPermanentFromButton;

// Sao chep vao clipboard (dung cho khoa API trong trang Cai dat)
function copyToClipboard(elementId, btn) {
  var el = document.getElementById(elementId);
  if (!el) return;
  var text = el.value !== undefined ? el.value : el.textContent;
  navigator.clipboard.writeText(text).then(function () {
    if (btn) {
      var old = btn.textContent;
      btn.textContent = "Đã chép!";
      setTimeout(function () { btn.textContent = old; }, 1500);
    }
  });
}
window.copyToClipboard = copyToClipboard;

