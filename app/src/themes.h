#pragma once

#include <QString>

class QApplication;

namespace app {

void applyTheme(QApplication& app, bool dark);
QString themeStyleSheet(bool dark);

}  // namespace app

