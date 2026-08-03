from app.api.files import infer_upload_file_type


def test_course_standard_filename_overrides_textbook_selection():
    assert (
        infer_upload_file_type("义务教育数学课程标准（2022年版）.pdf", "textbook")
        == "curriculum"
    )


def test_textbook_filename_overrides_curriculum_selection():
    assert infer_upload_file_type("七年级上册数学电子书.pdf", "curriculum") == "textbook"


def test_generic_filename_keeps_explicit_selection():
    assert infer_upload_file_type("数学资料.pdf", "curriculum") == "curriculum"
