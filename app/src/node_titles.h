#pragma once

#include <QString>

#include <string>

namespace app {

// Canonical Chinese display names for nodes / categories / parameter labels.
// Core layer keeps English canonical titles; the UI layer translates.
QString nodeTitle(const std::string& type, bool zh);
QString categoryTitle(const std::string& category, bool zh);
QString paramLabel(const std::string& label, bool zh);

}  // namespace app
