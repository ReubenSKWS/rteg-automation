

procedure(rdsBawClrAngForm()
let((cv instSel inst instName instCellName param clrStr clrMBAngList clrMTAngList sep1 sep2 sep2lbl sep3lbl fields angleChoice
      mbe1strEntry mbe1strKeysM mbe1strKeysP
      mbe1stpEntry mbe1stpKeysM mbe1stpKeysP

      mbe2strEntry mbe2strKeysM mbe2strKeysP
      mbe2stpEntry mbe2stpKeysM mbe2stpKeysP

      mte1strEntry mte1strKeysM mte1strKeysP
      mte1stpEntry mte1stpKeysM mte1stpKeysP

      mte2strEntry mte2strKeysM mte2strKeysP
      mte2stpEntry mte2stpKeysM mte2stpKeysP
    )

; println("version 1.0")

  cv = geGetWindowCellView()
  instSel = geGetSelSet()

  if( length(instSel) != 1 then
    rdsBasePopupMsg("Please select one resonator!")
    return( nil )
  );if

;  if(instSeled then
;    instSel = setof(x instSeled x~>objType == "inst")
;  );if

  inst = car( instSel )
  instName = inst~>name
  instCellName = inst~>cellName

  unless(rexMatchp( "^series" instCellName) || rexMatchp("^shunt" instCellName ) then
    rdsBasePopupMsg( "Please select one resonator!" )
    return( nil )
  );unless

  clrStr = "NONE"

  foreach( param cdfGetInstCDF(inst)~>parameters
    when( param->name == "claB"
      clrStr = param->value
      clrMBAngList = parseString( clrStr )
    )
    when(param->name == "claT"
      clrStr = param->value
      clrMTAngList = parseString( clrStr )
    )
  );foreach

  while(length(clrMBAngList) < 4
    clrMBAngList = append1(clrMBAngList "nil")
  )
  while(length(clrMTAngList) < 4
    clrMTAngList = append1(clrMTAngList "nil")
  )

;info(strcat( buildString(clrMBAngList) "\n"))
;info(strcat( buildString(clrMTAngList) "\n"))

;; The disclosure triangle
  sep1=hiCreateDisclosureTriangle(?name 'sep1
    ?labelText "Set Collar Start/Stop Angle"

;; Fields inside onFields remain ON by default
    ?onFields '()

;; Fields inside offFields will remain off by default
    ?offFields '(angleChoice mbe1strEntry mbe1strKeysM mbe1strKeysP mbe1stpEntry mbe1stpKeysM mbe1stpKeysP)
  )

;; The disclosure button

/*  angleChoice = hiCreateFloatField(
                  ?name  'angleChoice
                  ?prompt "Angle Increment"
                  ?value  15.0
                  ?editable t
  angKeysM =  hiCreateFormButton(
                ?name 'angKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(inst \"ang\" \"ang\" -1.0 angleChoice->value)"
              )
  angKeysP =  hiCreateFormButton(
                ?name 'angKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(inst \"ang\" \"ang\" 1.0 angleChoice->value)"
              )
*/
  angleChoice = hiCreateComboField(
                ?name  'angleChoice
                ?prompt "Angle Increment"
                ?items '("30.0" "15.0" "5.0" "1.0" "0.5" "0.1")
                ?format "%6s"
                ?value  "15.0"
                ?editable nil
              )

; MBE Collar 1
  mbe1strEntry = hiCreateStringField(
                  ?name  'mbe1strEntry
                  ?prompt "MBE Collar 1 Start Angle"
                  ?format "%6s"
                  ?value  nth(0, clrMBAngList)
                  ?editable t
                )
  mbe1strKeysM =  hiCreateFormButton(
                ?name 'mbe1strKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe1\" \"str\" -1.0 angleChoice->value)"
              )
  mbe1strKeysP =  hiCreateFormButton(
                ?name 'mbe1strKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe1\" \"str\" 1.0 angleChoice->value)"
              )
  mbe1stpEntry = hiCreateStringField(
                  ?name  'mbe1stpEntry
                  ?prompt "MBE Collar 1 Stop Angle"
                  ?format "%6s"
                  ?value  nth(1, clrMBAngList)
                  ?editable t
                )
  mbe1stpKeysM =  hiCreateFormButton(
                ?name 'mbe1stpKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe1\" \"stp\" -1.0 angleChoice->value)"
              )
  mbe1stpKeysP =  hiCreateFormButton(
                ?name 'mbe1stpKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe1\" \"stp\" 1.0 angleChoice->value)"
              )

; MBE Collar 2
  mbe2delEntry =  hiCreateFormButton(
                ?name 'mbe2delEntry
                ?buttonText "DEL"
;                ?invisible t
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe2\" \"del\" \"del\" angleChoice->value)"
              )
  mbe2addEntry =  hiCreateFormButton(
                ?name 'mbe2addEntry
                ?buttonText "ADD"
;                ?invisible t
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe2\" \"str\" 1.0 angleChoice->value)"
              )
  mbe2strEntry = hiCreateStringField(
                  ?name  'mbe2strEntry
                  ?prompt "MBE Collar 2 Start Angle"
                  ?format "%6s"
                  ?value  nth(2, clrMBAngList)
                  ?editable t
                )
  mbe2strKeysM =  hiCreateFormButton(
                ?name 'mbe2strKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe2\" \"str\" -1.0 angleChoice->value)"
              )
  mbe2strKeysP =  hiCreateFormButton(
                ?name 'mbe2strKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe2\" \"str\" 1.0 angleChoice->value)"
              )
  mbe2stpEntry = hiCreateStringField(
                  ?name  'mbe2stpEntry
                  ?prompt "MBE Collar 2 Stop Angle"
                  ?format "%6s"
                  ?value  nth(3, clrMBAngList)
                  ?editable t
                )
  mbe2stpKeysM =  hiCreateFormButton(
                ?name 'mbe2stpKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe2\" \"stp\" -1.0 angleChoice->value)"
              )
  mbe2stpKeysP =  hiCreateFormButton(
                ?name 'mbe2stpKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mbe2\" \"stp\" 1.0 angleChoice->value)"
              )

; MTE Collar 1
  mte1strEntry = hiCreateStringField(
                  ?name  'mte1strEntry
                  ?prompt "MTE Collar 1 Start Angle"
                  ?format "%6s"
                  ?value  nth(0, clrMTAngList)
                  ?editable t
                )
  mte1strKeysM =  hiCreateFormButton(
                ?name 'mte1strKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte1\" \"str\" -1.0 angleChoice->value)"
              )
  mte1strKeysP =  hiCreateFormButton(
                ?name 'mte1strKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte1\" \"str\" 1.0 angleChoice->value)"
              )

  mte1stpEntry = hiCreateStringField(
                  ?name  'mte1stpEntry
                  ?prompt "MTE Collar 1 Stop Angle"
                  ?format "%6s"
                  ?value  nth(1, clrMTAngList)
                  ?editable t
                )
  mte1stpKeysM =  hiCreateFormButton(
                ?name 'mte1stpKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte1\" \"stp\" -1.0 angleChoice->value)"
              )
  mte1stpKeysP =  hiCreateFormButton(
                ?name 'mte1stpKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte1\" \"stp\" 1.0 angleChoice->value)"
              )

; MTE Collar 2
  mte2delEntry =  hiCreateFormButton(
                ?name 'mte2delEntry
                ?buttonText "DEL"
;                ?invisible t
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte2\" \"del\" \"del\" angleChoice->value)"
              )
  mte2addEntry =  hiCreateFormButton(
                ?name 'mte2addEntry
                ?buttonText "ADD"
;                ?invisible t
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte2\" \"str\" 1.0 angleChoice->value)"
              )
  mte2strEntry = hiCreateStringField(
                  ?name  'mte2strEntry
                  ?prompt "MTE Collar 2 Start Angle"
                  ?format "%6s"
                  ?value  nth(2, clrMTAngList)
                  ?editable t
                )
  mte2strKeysM =  hiCreateFormButton(
                ?name 'mte2strKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte2\" \"str\" -1.0 angleChoice->value)"
              )
  mte2strKeysP =  hiCreateFormButton(
                ?name 'mte2strKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte2\" \"str\" 1.0 angleChoice->value)"
              )

  mte2stpEntry = hiCreateStringField(
                  ?name  'mte2stpEntry
                  ?prompt "MTE Collar 2 Stop Angle"
                  ?format "%6s"
                  ?value  nth(3, clrMTAngList)
                  ?editable t
                )
  mte2stpKeysM =  hiCreateFormButton(
                ?name 'mte2stpKeysM
                ?buttonText "-"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte2\" \"stp\" -1.0 angleChoice->value)"
              )
  mte2stpKeysP =  hiCreateFormButton(
                ?name 'mte2stpKeysP
                ?buttonText "+"
                ?callback "rdsBawClrAng(hiGetCurrentForm() inst \"mte2\" \"stp\" 1.0 angleChoice->value)"
              )

  fields = list(

    list(angleChoice 100:0 260:50 200 )
;    list(angKeysM 360:0 40:40 )
;    list(angKeysP 400:0 40:40 )

    list(mbe1strEntry 100:40 260:50 200 )
    list(mbe1strKeysM 360:40 40:40 )
    list(mbe1strKeysP 400:40 40:40 )
    list(mbe1stpEntry 100:80 260:50 200 )
    list(mbe1stpKeysM 360:80 40:40 )
    list(mbe1stpKeysP 400:80 40:40 )

    list(mbe2delEntry 10:140 40:40 )
    list(mbe2addEntry 50:140 40:40 )

    list(mbe2strEntry 100:120 260:50 200 )
    list(mbe2strKeysM 360:120 40:40 )
    list(mbe2strKeysP 400:120 40:40 )
    list(mbe2stpEntry 100:160 260:50 200 )
    list(mbe2stpKeysM 360:160 40:40 )
    list(mbe2stpKeysP 400:160 40:40 )

    list(mte1strEntry 100:220 260:50 200 )
    list(mte1strKeysM 360:220 40:40 )
    list(mte1strKeysP 400:220 40:40 )
    list(mte1stpEntry 100:260 260:50 200 )
    list(mte1stpKeysM 360:260 40:40 )
    list(mte1stpKeysP 400:260 40:40 )

    list(mte2delEntry 10:320 40:40 )
    list(mte2addEntry 50:320 40:40 )

    list(mte2strEntry 100:300 260:50 200 )
    list(mte2strKeysM 360:300 40:40 )
    list(mte2strKeysP 400:300 40:40 )
    list(mte2stpEntry 100:340 260:50 200 )
    list(mte2stpKeysM 360:340 40:40 )
    list(mte2stpKeysP 400:340 40:40 )
  )
  
  bawClrAngSetupGUIForm = hiCreateAppForm(
                              ?name 'bawInstRotSetupForm
                              ?formTitle "Collar Start/Stop Angle Form"
                              ?fields fields
                              ?initialSize t
                              ?buttonLayout 'OKCancel
                            );hiCreateAppForm

  hiDisplayForm('bawClrAngSetupGUIForm)
)
);rdsBawClrAngForm


procedure(rdsBawClrAng(theForm inst clrID strstp addsub deltaAngStr)
  prog( (instName instCellName PARAM param)

;  instName = inst~>name
;  instCellName = inst~>cellName

  deltaAng = atof(deltaAngStr)

  foreach( param cdfGetInstCDF(inst)~>parameters
    when( param->name == "claB"
      clrStr = param->value
      clrMBAngList = parseString( clrStr )
    )
    when(param->name == "claT"
      clrStr = param->value
      clrMTAngList = parseString( clrStr )
    )
  );foreach

  while(length(clrMBAngList) < 4
    clrMBAngList = append1(clrMBAngList "nil")
  )
  while(length(clrMTAngList) < 4
    clrMTAngList = append1(clrMTAngList "nil")
  )

  case( clrID
    ("mbe1"
      if( strstp == "str" then
        ang = sprintf( nil "%0.1f" (addsub * deltaAng) + atof(nth(0 clrMBAngList)) )
        theForm->mbe1strEntry->value = ang
        rplaca( nthcdr(0 clrMBAngList) ang )
      else
        ang = sprintf( nil "%0.1f" (addsub * deltaAng) + atof(nth(1 clrMBAngList)) )
        theForm->mbe1stpEntry->value = ang
        rplaca(nthcdr(1 clrMBAngList) ang )
      )
    )
    ("mbe2"
      case( strstp
        ("del"
          rplaca(nthcdr(2 clrMBAngList) "nil")
          theForm->mbe2strEntry->value = "nil"
          rplaca(nthcdr(3 clrMBAngList) "nil")
          theForm->mbe2stpEntry->value = "nil"
        );"del"
        ("str"
          if( (nth(2 clrMBAngList) == "nil") || (nth(3 clrMBAngList) == "nil") then
            ang = sprintf( nil "%0.1f" (deltaAng + atof(nth(1 clrMBAngList))) )
            rplaca(nthcdr(2 clrMBAngList) ang)
            theForm->mbe2strEntry->value = ang
            ang = sprintf( nil "%0.1f" (deltaAng + atof(ang)) )
            rplaca(nthcdr(3 clrMBAngList) ang)
            theForm->mbe2stpEntry->value = ang
          else  
            ang = sprintf( nil "%0.1f" (addsub * deltaAng) + atof(nth(2 clrMBAngList)) )
            theForm->mbe2strEntry->value = ang
            rplaca(nthcdr(2 clrMBAngList) ang )
          )
        );"str"
        ("stp"
          if( (nth(2 clrMBAngList) == "nil") || (nth(3 clrMBAngList) == "nil") then
            ang = sprintf( nil "%0.1f" (deltaAng + atof(nth(1 clrMBAngList))) )
            rplaca(nthcdr(2 clrMBAngList) ang)
            theForm->mbe2strEntry->value = ang
            ang = sprintf( nil "%0.1f" (deltaAng + atof(ang)) )
            rplaca(nthcdr(3 clrMBAngList) ang)
            theForm->mbe2stpEntry->value = ang
          else  
            ang = sprintf( nil "%0.1f" (addsub * deltaAng) + atof(nth(3 clrMBAngList)) )
            theForm->mbe2stpEntry->value = ang
            rplaca(nthcdr(3 clrMBAngList) ang )
          )
        );"stp"
      );case strstp
    );"mbe2"
    ("mte1"
      if( strstp == "str" then
        ang = sprintf( nil "%0.1f" (addsub * deltaAng) + atof(nth(0 clrMTAngList)) )
        theForm->mte1strEntry->value = ang
        rplaca(nthcdr(0 clrMTAngList) ang )
      else
        ang = sprintf( nil "%0.1f" (addsub * deltaAng) + atof(nth(1 clrMTAngList)) )
        theForm->mte1stpEntry->value = ang
        rplaca(nthcdr(1 clrMTAngList) ang )
      )
    )
    ("mte2"
      case( strstp
        ("del"
          rplaca(nthcdr(2 clrMTAngList) "nil")
          theForm->mte2strEntry->value = "nil"
          rplaca(nthcdr(3 clrMTAngList) "nil")
          theForm->mte2stpEntry->value = "nil"
        );"del"
        ("str"
          if( (nth(2 clrMTAngList) == "nil") || (nth(3 clrMTAngList) == "nil") then
            ang = sprintf( nil "%0.1f" (deltaAng + atof(nth(1 clrMTAngList))) )
            rplaca(nthcdr(2 clrMTAngList) ang)
            theForm->mte2strEntry->value = ang
            ang = sprintf( nil "%0.1f" (deltaAng + atof(ang)) )
            rplaca(nthcdr(3 clrMTAngList) ang)
            theForm->mte2stpEntry->value = ang
        else
          ang = sprintf( nil "%0.1f" (addsub * deltaAng) + atof(nth(2 clrMTAngList)) )
          theForm->mte2strEntry->value = ang
          rplaca(nthcdr(2 clrMTAngList) ang )
          )
        );"str"
        ("stp"
          if( (nth(2 clrMTAngList) == "nil") || (nth(3 clrMTAngList) == "nil") then
            ang = sprintf( nil "%0.1f" (deltaAng + atof(nth(1 clrMTAngList))) )
            rplaca(nthcdr(2 clrMTAngList) ang)
            theForm->mte2strEntry->value = ang
            ang = sprintf( nil "%0.1f" (deltaAng + atof(ang)) )
            rplaca(nthcdr(3 clrMTAngList) ang)
            theForm->mte2stpEntry->value = ang
          else  
            ang = sprintf( nil "%0.1f" (addsub * deltaAng) + atof(nth(3 clrMTAngList)) )
            theForm->mte2stpEntry->value = ang
            rplaca(nthcdr(3 clrMTAngList) ang )
          )
        );"stp"
      );case strstp
    );"mte2"

  );case clrID

  clrMBAngList = remove("nil" clrMBAngList)
  clrMTAngList = remove("nil" clrMTAngList)

;info(strcat( buildString(clrMBAngList) "\n"))
;info(strcat( buildString(clrMTAngList) "\n"))

  foreach( param cdfGetInstCDF(inst)~>parameters
    when( param->name == "claB"
      param->value = buildString(clrMBAngList)
    )
    when(param->name == "claT"
      param->value = buildString(clrMTAngList)
    )
  );foreach

);prog
);procedure
