# Exact source identity is checked by c100x_display.sh before this transform.
function include(path, line) {
    while ((getline line < path) > 0) {
        gsub(/@RELEASE@/, release, line)
        print line
    }
    close(path)
}
mode == "main" && $0 == "    property bool onlyAudio: false" {
    print
    include(hooks "/main.inc")
    inserted++
    next
}
mode == "main" && $0 == "                    if (pageName === \"settings\") {" {
    print "                    if (pageName === \"c100x\") {"
    print "                        if (c100xHost && !c100xHost.blocked) mainStackView.goToPage(c100xPage, imageUrl)"
    print "                    } else if (pageName === \"settings\") {"
    navigation++
    next
}
mode == "menu" && $0 == "    id: root" {
    print
    include(hooks "/menu.inc")
    inserted++
    next
}
mode == "menu" && $0 == "            listModel.append( { sourceImg: \"images/Exit.svg\",component: onlyIcon })" {
    print
    print "            root.syncC100xMenu()"
    navigation++
    next
}
{ print }
END { if (inserted != 1 || navigation != 1) exit 1 }
