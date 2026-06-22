;;GUI
fNameLastValue = " "
;;fNameLastValue = "/prj/amslib/work/yangj1/baw/bawpdk4/v105/baw_quad_TEG_DOE_sample.csv"
;; v1, 04/20/2023, baw 2 5, v 1. 07, by yangj1
;; for high AR Resonator and mimcap DOE
;; restype can be mimcap, highARRes, quad, frame, most code is if !mimcap then xxx
procedure(rdsBawTEGcsvDOEGUI(restype)
    prog( (cvId defaultLibName defaultCellName defaultViewName libNames cellNames viewNames fName 
    		sprtBrowse fileBrowse smplFile  lName cName vName frMB2Chk frlcv frMB2lib frMB2cel frMB2view 
    		frmW frmL maxNum  pbtp ptch ppdRot ppdExt TEGWid tsvChk  gndChk autoRot relChk  fields 
    		extraFields y i BawMimCapTEGfromCSVDOEForm )

        cvId = geGetEditCellView()
        libNames = sort(ddGetLibList()~>name 'alphalessp)

        if(cvId then
            defaultLibName  = cvId~>libName
	    	defaultCellName = cvId~>cellName
	    	defaultViewName = cvId~>viewName
		else
	    	defaultLibName  = car(libNames)
	    	defaultCellName = car(ddGetObj(defaultLibName)~>cells)~>name
	    	defaultViewName = car(ddGetObj(defaultLibName defaultCellName)~>views)~>name			
		)
		
		cellNames = sort(ddGetObj(defaultLibName)~>cells~>name 'alphalessp)                	
		viewNames = ddGetObj(defaultLibName defaultCellName)~>views~>name   
        
		case(restype
        	("mimcap"  		
        		tlt = "Create BAW Mimcap RTEGs from CSV DOE... "
        		sampleFileCB = "rdsbawTEGSprtBrowseFile(6)" )
        	("highARRes"  	
        		tlt = "Create Mesh Resonator RTEGs from CSV DOE..." 
        		sampleFileCB = "rdsbawTEGSprtBrowseFile(7)")
        	("quad" 	
        		tlt = "Create Quadrilateral Resonator RTEGs from CSV DOE..." 
        		sampleFileCB = "rdsbawTEGSprtBrowseFile(8)")
        );;case  
        
             
		fName = hiCreateStringField(   ?name  	'fName
                                       ?prompt 	"CSV File:"
                                       ?value    fNameLastValue
                                      ;; ?value    "/prj/amslib/work/yangj1/baw/bawpdk4/v107/baw_mimcap_TEG_DOE_sample.csv"
                                       ?callback "rdsbawfNameCB( hiGetCurrentForm() )"
                                       )         

        sprtBrowse = hiCreateFormButton(   ?name          'sprtBrowse
                                   	   ?buttonText     "Browse File ..."
                                   	   ?callback      "ddsFileBrowseCB(hiGetCurrentForm()  'fName \"*.csv\" 'existingFile )"
                                  	   ) 
        fileBrowse = hiCreateFormButton(   ?name          'fileBrowse
                                   	   ?buttonText      "View Browsed File ..."
                                   	   ?callback       "rdsbawTEGSprtBrowseFile(1)"
                                  	   )   
        smplFile   = hiCreateFormButton(   ?name          'smplFile
                                   	   ?buttonText     "Sample CSV ..."
                                   	   ?callback       sampleFileCB
                                  	   )                                      	                                   	                                       
        lName = hiCreateComboField(  	?name           'lName
				     			        ?prompt         "Create in library:"
				     			        ?items          libNames
				     			        ?value          defaultLibName   		
				     			       ;;?value          "test_v105"   		     			        
                                      	)                                     
        cName = hiCreateStringField(  ?name           'cName
				     			      ?prompt         "TEG basename:"   
				     			      ?value          defaultCellName   	  
				     			      ;;?value          "test_mim"  		
           			      )
        frMB2Chk = hiCreateBooleanButton( ?name 'frMB2Chk
		                                    ?buttonText "Create frame and MB2 patterns?"
		                                    ?value t
		                                    ?callback       "form = hiGetCurrentForm()
		                                    				rdsBawTEGSprtFrameMB2CB(form)"
                                       )	

        frlcv =  hiCreateLabel( ?name 'frlcv
								?labelText 	"Select frame and MB2 library, cell and view:"
							  )              
									              
        frMB2lib = hiCreateComboField(  ?name           'frMB2lib
		         			   ;;     	?prompt         "Library:"
		         			        	?items          libNames
		         			        	?value          defaultLibName    
		         			        	?invisible 		nil
		         			        	?callback      "form = hiGetCurrentForm()             			
								 						form->frMB2cel->items = sort(ddGetObj(form->frMB2lib->value)~>cells~>name 'alphalessp)
								 						form->frMB2cel->value = car(form->frMB2cel->items)	
									 					form->frMB2view->items = sort(ddGetObj(form->frMB2lib->value form->frMB2cel->value)~>views~>name 'alphalessp)				                 
								 						form->frMB2view->value = car(sort(ddGetObj(form->frMB2lib->value form->frMB2cel->value)~>views~>name 'alphalessp)) 
								 						ddsUpdateSyncWithForm()"
             			        	
                                      	)    
        frMB2cel = hiCreateComboField(  ?name           'frMB2cel
		         			  ;;      	?prompt         "Cell:"
		         			        	?items          cellNames
		         			        	?value          defaultCellName  
		         			        	?invisible 		nil
		         			        	?callback       "form = hiGetCurrentForm()             			
														 form->frMB2view->items = sort(ddGetObj(form->frMB2lib->value form->frMB2cel->value)~>views~>name 'alphalessp)				                 
								 						form->frMB2view->value = car(sort(ddGetObj(form->frMB2lib->value form->frMB2cel->value)~>views~>name 'alphalessp)) 
														 ddsUpdateSyncWithForm()" 
                                      	)       
        frMB2view = hiCreateComboField(  ?name           'frMB2view
		         			  ;;      	?prompt         "View:"
		         			        	?items          viewNames
		         			        	?value          defaultViewName   
		         			        	?invisible 		nil 
		         			        	?callback       "ddsUpdateSyncWithForm()"    
                                      )  
                                      	                                      	                                  	                                               	     
        frmW = hiCreateStringField(   ?name  	'frmW
                                      ?prompt 	"X Spacing (um):"
                                      ?value  	"0.0"
                                      ?enabled 		nil
                                      ?callback "spaceCallBack(1)"
                                                 
                                      )  
        frmL = hiCreateStringField(   ?name  	'frmL
                                      ?prompt 	"Y Spacing (um):"
                                      ?value 	"0.0"
                                      ?enabled     nil
                                      ?callback "spaceCallBack(2)"
                                      )                                                            

        pbtp = hiCreateCyclicField(?name 'pbtp
                                     ?prompt "Probe Type"
                                     ?choices list("GS" "SG" "GGS" "GSG")      
                                     ;;?callback  "rdsbawppdCB()"  
                                     ?defValue "GSG" 
;;                                     ?invisible t
									?enabled nil
                                     )    
        ptch = hiCreateCyclicField(?name 'ptch
                                     ?prompt "Pitch Size"
                                     ?choices list("142.5 um"  "150 um"  "300 um" "450 um" "600 um" )
                                     ?defValue "150 um"
;;                                     ?invisible t
                                     )  
        pdtp = hiCreateCyclicField(?name 'pdtp
                                     ?prompt "Probe Pad Type"
                                     ?choices list("TYPE1"  "TYPE2")      
                                     ?defValue "TYPE1" 
                                     )                                      							                    
        ppdRot = hiCreateCyclicField(?name 'ppdRot 
                                     ?prompt "Probe Pad Location"
                                     ?choices list("left" "right" "top" "bottom")         
                                     ?defValue "left"
                                     ?enabled nil
                                     )     
        ppdExt = hiCreateStringField( ?name  	'ppdExt
                                      ?prompt 	"Probe Pad Y-Extension:"
                                      ?value  	"0.0"                                                
                                      )   
        TEGWid = hiCreateStringField( ?name  	'TEGWid
                                      ?prompt 	"RTEG Overall Width:"
                                      ?value  	"376.0"                                                
                                      )
                                                                                                                             
        tsvChk = hiCreateBooleanButton( ?name 'tsvChk
                                        ?buttonText "TEG with TSV"
                                        ?value nil
;;										?invisible t
                                       )
        gndChk = hiCreateBooleanButton( ?name 'gndChk
                                        ?buttonText "Add Ground Bar"
                                        ?value nil
                                       )                               
        autoRot = hiCreateBooleanButton( ?name 'autoRot
                                        ?buttonText "Automatically Rotate Resonator"
                                        ?value t
                                       )   
        num = hiCreateStringField( ?name  	'num
                                      ?prompt 	"Number of TEGs per row:"
                                      ?value  	"20"                                                
                                      )                                                                                                     
        fields = list(
                      list(fName 0:0 850:30 230 )
                      list(sprtBrowse 230:30 120:30)
                      list(fileBrowse 380:30 220:30)   
                      list(smplFile   630:30 200:30)                   
                      list(lName  0:60 450:30 230 )
					  list(cName  0:90 450:30 230 )  
					  list(frMB2Chk 0:120 450:30 230)
					  list(frlcv 30:150 400:30 400)
					  list(frMB2lib 30:180 250:30 10 )
					  list(frMB2cel 310:180 300:30 10 )
					  list(frMB2view 660:180 150:30 10 )
					 )
		;;extraFields = list(frmW frmL pbtp ptch pdtp ppdRot ppdExt TEGWid tsvChk gndChk autoRot num)
		extraFields = list(frmW frmL pbtp ptch pdtp ppdRot ppdExt TEGWid tsvChk  num)
		y = 210
		for(i 0 length(extraFields)-1
			fields = append1(fields list(nth(i extraFields) 0:y+30*i 450:30 230))
		);;for                                                                      
        
                                     
		
        BawTEGcsvDOEForm = hiCreateAppForm( ?name 'BawTEGcsvDOEForm
                                       ?formTitle  tlt
                                       ?fields     fields    
                                       ?initialSize t
                                       ?callback "form = hiGetCurrentForm() 
                                       			  rdsBawTEGcsvDOECB(form restype) "
                                       ?buttonLayout 'OKCancelApply
                                       )        

        hiDisplayForm('BawTEGcsvDOEForm)
        
        return(t)     
    );;prog
);;procedure






procedure(rdsBawCSVReadFile(file restype @optional promptTBExtra)
prog( (headers data fptr sharp bkt spc line subline relist)    
    ;;restype can be "frame" or other instance name
	;;promptTBExtra is to cover those not in the function list
	;;return list of instance parameters and instance name
		
		    
    headers = nil
    data = nil	
    prompts = nil
	unless(isFile(file) 
		rdsBasePopupMsg("File doesn't exist!!")
		return(nil)	
	);;unless
	fptr = infile(file)
	;;compile #, () and last white space
	sharp = pcreCompile("^ *#")
	bkt = pcreCompile("\\(.*\\)")
	spc = pcreCompile(" +$")
	while(gets(line fptr)	  
		;;remove "\n"
		line = substring(line, 1, strlen(line)-1)
		;;skip blank lines
		unless(blankstrp(line)
			;get header starts with "#"			
			if(pcreExecute(sharp line) then 
				subline = pcreReplace(sharp line "" 0)
				header = parseString(subline "," t)
				header = foreach(mapcar str header pcreReplace(bkt str "" 0))
				header = foreach(mapcar str header pcreReplace(spc str "" 0))
				if(promptTBExtra then
					prompts = rdsBawCSVConvertHeader(header restype promptTBExtra)
				else
					prompts = rdsBawCSVConvertHeader(header restype)
				);;if
			else 				
				data = tconc(data parseString(line "," t))
			);if
		);unless
	); while

	close(fptr)	
	data = car(data)
	relist = list(data prompts )
	return(relist)   

))


/*
procedure(rdsBawCSVPromptType(header promptTB @optional promptTBExtra)
	prog( (typeTB strList boolList trimList i ele)
		;;promptTBExtra is a list of list("cdfName" "promptType")
		;;eg. promptTBExtra = list( list("mbeClr" "string") list("mteClr" "string") )
		typeTB = makeTable('typeTB "")
		strList = list("ModelId" "Process" "Band" "Fab" "ReW" "MRaW" "ToCalc" "SV_thickness" "c" "l" "w" "rot"
						"Term1_Top" "Term1_Left" "Term1_Right" "Term2_Lay" "Term2_Len" "devType" "A" "Fs" "ORaW"
						"ORaWBT" "cla" "spm" "cDir" "aRel" "arlC" "AspectR" "AspectRot" "smthangl" "smthR" 
						"SharpPts" "SharpR" "vtbfc" "apang" "AddTrim" "frW" "frL" "cvt")
		boolList = list("ADR" "TEG" )
		intList = list("INFRA_ver" )
		trimList = list()
		for(i 1 6
			foreach(ele list("MF" "TF")
				trimList = append(trimList  list(strcat(ele sprintf(nil "%d" i) " Trim")   strcat(ele sprintf(nil "%d" i)) ) )
			);;foreach
		);;for
		boolList = nconc(boolList trimList)
		foreach(ele strList typeTB[ele] = "string" )
		foreach(ele boolList typeTB[ele] = "boolean")
		foreach(ele intList typeTB[ele] = "integer")
		
		foreach(ele promptTBExtra typeTB[car(ele)] = nth(1 ele))
		return(typeTB)
	);;prog
);;proc
*/


procedure(rdsBawCSVConvertHeader(header restype @optional headerExtra)
	prog( (promptTB idList id i ele str prompts)
		;;headerExtra is a list of list("promptName" "cdfName"). 
		;;eg. headerExtra = list( list("MBE Collar" "mbeClr")  list("MTE Collar" "mteClr"))
		
		;;common
		promptTB = makeTable('promptTB "")
		idList = list("ModelID" "Process" "Band" "Fab" "ADR" "ReW" "MRaW" "TEG" )
		foreach(id idList promptTB[id] = id)
		promptTB["INFRA Version"] = "INFRA_ver"		
		promptTB["Device Type"] = "devType"   promptTB["Type"] = "devType"
		promptTB["Rotate Angle"] = "rot"
		
		;;cap
		promptTB["Calculate"] = "ToCalc"
		promptTB["SV Thickness"] = "SV_thickness"
		promptTB["Capacitance"] = "c"  promptTB["Capacitance (fF)"] = "c"  promptTB["Capacitance (F)"] = "c"  promptTB["capacitance"] = "c"
		promptTB["Length"] = "l" promptTB["Length (um)"] = "l"  promptTB["Length(um)"] = "l"  promptTB["length (um)"] = "l"
		promptTB["Width"] = "w"  promptTB["Width (um)"] = "w"   promptTB["Width(um)"] = "w"   promptTB["width (um)"] = "w"
		promptTB["Chamfer"] = "cham"  promptTB["Chamfer (um)"] = "cham"  promptTB["Chamfer(um)"] = "cham"  promptTB["chamfer (um)"] = "cham"
		promptTB["Open Short"] = "OpenShort"		
		promptTB["Term1 Top"] = "Term1_Top"
		promptTB["Term1 Left"] = "Term1_Left" 
		promptTB["Term1 Right"] = "Term1_Right" 
		promptTB["Term2 Layer"] = "Term2_Lay"
		promptTB["Term2 Length"] = "Term2_Len"
		
		;;resonator
		promptTB["Area"] = "A"
		promptTB["Freq Target"] = "Fs"
		promptTB["ORaW (MBE)"] = "ORaW"
		promptTB["ORaW"] = "ORaW"
		promptTB["ORaW offset (MTE)"] = "ORaWBT"
		promptTB["ORaW offset"] = "ORaWBT"
		promptTB["ORaW (MBE)"] = "ORaW"
		promptTB["ORaW offset (MTE)"] = "ORaWBT"
		promptTB["CutLine Angle"] = "cla"
		promptTB["CutLine Spacing"] = "spm"
		promptTB["Swap Collars"] = "cDir" 
		promptTB["Add REL Cells"] = "aRel"
		promptTB["REL Deg at Origin"] = "arlC"
		promptTB["Rotate Angle"] = "rot"
		promptTB["Aspect Ratio"] = "AspectR"
		if(restype == "quad" then 
			promptTB["Aspect Ratio"] = "AR" 
			promptTB["Aspect Ratio Scaling"] = "AR" 
		);;if)
		promptTB["Aspect Ratio Rotate Angle"] = "AspectRot"
		promptTB["Smoothing Angle"] = "smthangl"
		promptTB["Smothing Ratio"] = "smthR"
		promptTB["Points"] = "SharpPts"
		promptTB["Radius"] = "SharpR"
		promptTB["VTB Faces"] = "vtbfc"
		promptTB["Long Side Angle"] = "apang"
		promptTB["Short Side Angle"] = "ssa"
		promptTB["Add Trim Layers"] = "AddTrim"
		;;for frame, TFx~MFx, for resonator TFx~MFx/TFx~MFx_Trim
		if(restype == "frame" then
			for(i 1 6
				promptTB[strcat("MF" sprintf(nil "%d" i))] = strcat("MF" sprintf(nil "%d" i))
				promptTB[strcat("TF" sprintf(nil "%d" i))] = strcat("TF" sprintf(nil "%d" i))		
			);;for
			promptTB["TFS"] = "TFS"
			promptTB["TFP"] = "TFP"
		else
			for(i 1 6				
				promptTB[strcat("MF" sprintf(nil "%d" i) " Trim")] = strcat("MF" sprintf(nil "%d" i) "_Trim")
				promptTB[strcat("TF" sprintf(nil "%d" i) " Trim")] = strcat("TF" sprintf(nil "%d" i) "_Trim")	
				promptTB[strcat("MF" sprintf(nil "%d" i))] = strcat("MF" sprintf(nil "%d" i) "_Trim")
				promptTB[strcat("TF" sprintf(nil "%d" i))] = strcat("TF" sprintf(nil "%d" i) "_Trim")			
			);;for
			promptTB["TFS Trim"] = "TFS_Trim"
			promptTB["TFP Trim"] = "TFP_Trim"
			promptTB["TFS"] = "TFS_Trim"
			promptTB["TFP"] = "TFP_Trim"
		);;if
		
		;;frame
		promptTB["Frame Width"] = "frW"
		promptTB["Frame Height"] = "frL"
		promptTB["Cavity Layer"] = "cvt"
		
		;;extra
		if(headerExtra then
			foreach(ele headerExtra
				promptTB[car(ele)] = nth(1 ele)
			);;foreach
		);;if
		prompts = foreach(mapcar str header promptTB[str])
		return(prompts)
	);;prog
);;proc



procedure(rdsBawTEGSprtFrameMB2CB(form)
	let( (frMB2Chk frMB2lib frMB2cel frMB2view frmW frmL )
		frMB2Chk = 	form->frMB2Chk->value
		frMB2lib = 	form->frMB2lib
		frMB2cel = 	form->frMB2cel
		frMB2view = form->frMB2view
		frmW = form->frmW
		frmL = form->frmL
		if( frMB2Chk == t then
			frMB2lib -> enabled  = t
			frMB2cel -> enabled  = t
			frMB2view -> enabled  = t
			frmW -> enabled  = nil
			frmL -> enabled  = nil
		else
			frMB2lib -> enabled  = nil
			frMB2cel -> enabled  = nil
			frMB2view -> enabled  = nil
			frmW -> enabled  = t
			frmL -> enabled  = t
		)
			
	
	);;let
);;proc



;;;;;;;;For MIMcap DOE and high AR resonator DOE RTEGs;;;;;;;;;;;;;;;;;;;;;;;;;;
procedure(rdsBawTEGcsvDOECB(form restype)
	prog( (lName cName fName frMB2Chk num TEGWidValue tsvChk tsvValue pbtp ptch pdtp ppdExt relist prompts data
			topcv techLib instType instlay instlaysh masterLibs lib d2 d3 errmsg sh ppdlay vtblay p1 prop 
			frMB2lib frMb2cel frMB2view varName bkcv ints frms padbes cellW cellL ppdVar ppdTmp ptchValue 
			ptchnames ptchlist ptchname ppdparmlist ppdParmListTemp ppdDstTmp ppdLen txtSHps mbePad 
			padbbx mbePadLen mbeShps ppdTop ppdBot ppdRight ppdLeft shp	ints frms frame kpbbx ppdy ppdx ppdCoord 
			vtbLenPOR vtbLenADR vtbdx vtbWid vtbCoordY vtbCoordX vtbparmlist rectLL rectUR rectbbx  
			rowIndx colIndx inst instName cvName tegcv clay devTypeValue param i ele prompt valueType 
			FabValue SharpPts lsa Area ORaWVAlue MRaWValue ReWValue ADRValue sla cla1 cla2 claValue param 
			newInst ppdExtraList ppdParms ppdDst vtbL vtbParms vtbDst MTERect instY instbbx instdx instX newInst 
			pb frame trimlist connPolys mteConn mbeConn res shps resConnList tmp1 tmp2 )

		;;get all parameters from form
		lName = form->lName->value
		cName = form->cName->value
		fName = form->fName->value
		frMB2Chk = form->frMB2Chk->value
		num = evalstring(form->num->value)
		TEGWidValue = evalstring(form->TEGWid->value)
		tsvChk = form->tsvChk->value
		if(tsvChk then tsvValue = "Yes" else tsvValue = "No")
		pbtp = form->pbtp->value
		ptch = form->ptch->value
		pdtp = form->pdtp->value
		ppdExt = form->ppdExt->value
		
		;;convert csv to list of data + prompt
		relist = rdsBawCSVReadFile(fName restype)
		prompts = nth(1 relist)
		data = car(relist)
				
	
		;;create top cv and place each RTEG in top cv
		topcv = dbOpenCellViewByType(lName cName "layout" "maskLayout" "w")
		techLib = env(RDS_CDS_TECH)
		printf("Creating top cellview %s to %s...\n" cName lName)
		
		
		;;get resonator/mimcap master id and set of parameters with its cdf name and restype
		;;eg. prop = list of list(cdf_name  restype )
		case(restype 
			("highARRes"
				instType = nth(1 car(data))
				if(rexMatchp("^seriesm[0-9]" instType) || rexMatchp("^shuntm[0-9]" instType) then
					instlay = dbOpenCellViewByType(techLib "seriesm3" "layout")	
					instlaysh = dbOpenCellViewByType(techLib "shuntm3" "layout")	
				);;if
			);;highar
			("quad"
				instType = nth(1 car(data))
				if(rexMatchp("^seriesq[0-9]" instType) || rexMatchp("^shuntq[0-9]" instType) then
					masterLibs = list(techLib strcat(techLib "_dev") strcat(techLib "_research"))
					foreach(lib masterLibs
						if( member(instType ddGetObj(lib)~>cells~>name) then mstLib = lib)
					);;foreach
					d2 = foreach(mapcar dd data nth(1 dd))
					d3 = removeListDuplicates(d2)
					unless(length(d3)<=2
						errmsg = "This utility only allows no more than 2 types of resonator cell name.\neg. seriesq3, shuntq3\nSource file contains more than 2 types.\nPlease check your spreadsheet/csv.\n "
						rdsBasePopupError(errmsg)
						return(nil)
					);;unless 
					if(rexMatchp("^series" instType) then
						rexCompile("series")
						sh = rexReplace(instType "shunt" 1)
						instlay = dbOpenCellViewByType(mstLib instType "layout")	
						instlaysh = dbOpenCellViewByType(mstLib sh "layout")
					else
						rexCompile("shunt")
						sh = rexReplace(instType "series" 1)
						instlay = dbOpenCellViewByType(mstLib sh "layout")	
						instlaysh = dbOpenCellViewByType(mstLib instType "layout")
					);;if
				);;if				
			);;quad	
			("mimcap"
				instType = "mimcap_chamfer"
				;;instlay = dbOpenCellViewByType(techLib "mimcap" "layout")
				;;ppdlay = dbOpenCellViewByType(techLib "ppd" "layout")
				instlay = dbOpenCellViewByType(strcat(techLib "_research") "mimcap_chamfer" "layout")
			);;mimcap
		);;case	
		
		vtblay = dbOpenCellViewByType(techLib "vtb2" "layout")	
		ppdlay = dbOpenCellViewByType(techLib "ppd_1port" "layout")			
		p1 = car(setof(x instlay~>prop rexMatchp("parameters" x~>name))) 
		prop = foreach(mapcar x p1~>value list(x~>name x~>valueType))
		
	
		;;copy frMB2 cell to tmpLay, extract frame/padbe and w/l
		if(frMB2Chk then
			frMB2lib = form->frMB2lib->value
			frMB2cel = form->frMB2cel->value
			frMB2view = form->frMB2view->value
			frMB2cv = dbOpenCellViewByType(frMB2lib frMB2cel frMB2view)    
			varName = strcat(cName "_frMB2Tmp") 
			rdsBawCopyCelltoLib(frMB2lib frMB2cel varName lName)
			dbClose(frMB2cv)   
				            	    
		    bkcv = dbOpenCellViewByType(lName varName "layout" "maskLayout" "a")
			ints = dbInstQuery(bkcv bkcv~>bBox)			
			frms = setof(x ints atom(x)&& rexMatchp("^frame" x~>cellName) )		
			padbes = setof(aa ints atom(aa)&&rexMatchp("^padbe" aa~>cellName) )		
		
			cellW = rightEdge(bkcv~>bBox)-leftEdge(bkcv~>bBox)
			cellL = topEdge(bkcv~>bBox)-bottomEdge(bkcv~>bBox)
						
		else
			cellW = evalstring(form->frmW->value)
			cellL = evalstring(form->frmL->value)
		);;if
		
		
	
		ppdVar = strcat(cName "_ppdTmp")
		ppdTmp = dbOpenCellViewByType(lName ppdVar "layout" "maskLayout" "w")	
		
		;;get vtb coordinates for ADR and POR: create ppd->flatten->find "S" text->get mbePad = MBE overlaps "S"
		;;vtbCoordY = cadr(centerBox(mbePad)), vtbCoordX = rightEdge(mbePad)+vtbdx
		;;vtbLen = mbePadLenghth+2*7/6
		
		ptchValue = car(parseString(ptch " ")) 
	   	if(ptchValue == "142.5" then 
	   		ptchValue = strcat("pitch_" "142p5") 
	   	else
	   		ptchValue = strcat("pitch_" ptchValue)  
	   	)		
		ptchnames = list("pitch_142p5"  "pitch_150" "pitch_200" "pitch_250" "pitch_300" "pitch_350" "pitch_400" "pitch_450" "pitch_600" )
		ptchlist = list()
		foreach(ptchname ptchnames
			if(ptchname == ptchValue then ptchChk = t  else ptchChk = nil)
			ptchlist = append1(ptchlist  list(ptchname "boolean" ptchChk) )
		)
		ppdparmlist = list( list("TSV" "string" tsvValue ) 						list("MRY" "string" "No") 	
							list( "ptype" "string" pdtp)   						list("probe_type" "string" "GSG") 									
							list("Ext" "string" ppdExt)   						list("probeDir" "boolean" t) 																			
						)						
		ppdparmlist = append(ppdparmlist ptchlist)
		ppdParmListTemp = append(ppdparmlist list(list("ResonatorType" "string" "series")  list("ADR" "boolean" t)  list("AddLbl" "boolean" nil)  ))			
		ppdDstTmp = dbCreateParamInst(ppdTmp ppdlay nil list(0 0) "R0" 1 ppdParmListTemp  t) 
		ppdLen = topEdge(ppdDstTmp~>bBox)-bottomEdge(ppdDstTmp~>bBox)
		if(!frMB2Chk then
			cellW = cellW + TEGWidValue
			cellL = cellL + ppdLen
		);;if
		dbFlattenInst(ppdDstTmp 1 t)
		txtShps = setof(ele ppdTmp~>shapes ele~>layerName == "text" && ele~>objType == "label" && ele~>theLabel == "S")
		;;txtOrient = car(txtShps)~>orient		
		mbePad = car(dbGetTrueOverlaps(ppdTmp car(txtShps)~>bBox list("BAW_MBE")))
		padbbx = mbePad~>bBox
		mbePadLen = topEdge(padbbx)-bottomEdge(padbbx)
		mbeShps = setof(ele ppdTmp~>shapes ele~>layerName == "BAW_MBE" )
		ppdTop   = apply('max foreach(mapcar shp mbeShps topEdge(shp~>bBox)))
		ppdBot 	 = apply('min foreach(mapcar shp mbeShps bottomEdge(shp~>bBox)))
		ppdRight = apply('max foreach(mapcar shp mbeShps rightEdge(shp~>bBox)))
		ppdLeft  = apply('min foreach(mapcar shp mbeShps leftEdge(shp~>bBox)))
		foreach(shp ppdTmp~>shapes dbDeleteObject(shp))
		
		
		;;get ppd coordinates
		if(frMB2Chk then
			ints = dbInstQuery(bkcv bkcv~>bBox)			
			frms = setof(x ints atom(x)&& rexMatchp("^frame" x~>cellName) )		
			frame = dbCopyFig(car(frms) ppdTmp  list(0:0 "R0" 1))
			dbFlattenInst(frame 1 t)
			kpbbx = car(setof(x ppdTmp~>shapes x~>layerName == "BAW_KpOut"))~>bBox
			ppdy = cadr(centerBox(kpbbx))- cadr(centerBox(padbbx))
			ppdx = 0.5*(leftEdge(kpbbx)+rightEdge(kpbbx)-TEGWidValue)
			ppdCoord = list(ppdx ppdy)
			foreach(shp ppdTmp~>shapes dbDeleteObject(shp))
			
			ppdTop += cadr(ppdCoord)
			ppdBot += cadr(ppdCoord)
			ppdLeft += car(ppdCoord)
			ppdRight += car(ppdCoord)

		else
			ppdx = 0.0
			ppdy = 0.0
			ppdCoord = list(ppdx ppdy)
			
		);;if
		
		vtbLenPOR = mbePadLen + 2.0*7.0
		vtbLenADR = mbePadLen + 2.0*6.0
		vtbdx = 9.0
		vtbWid = 19.0
		vtbCoordY = cadr(centerBox(padbbx)) 
		vtbCoordX = rightEdge(padbbx)+vtbdx
		if(frMB2Chk then
			vtbCoordY += ppdy
			vtbCoordX += ppdx
		);;if
		vtbparmlist = list(list("Corner" "string" "FALSE") 			list("Extension" "boolean" nil) 
		                   list("mbeExt" "float" 0.0) 				list("padConn" "boolean" t ) 			 
		                 )			
		
				
		;;connect vtb MTE with 5 um rectangle 
		rectLL = list( rightEdge(padbbx)+vtbWid+ppdx   bottomEdge(padbbx)+ppdy )
		rectUR = list( car(rectLL)+5.0		  	   	   topEdge(padbbx)+ppdy    )
		rectbbx = list(rectLL rectUR )		
		
		

		
		;;create instance and copy to top cv
		rowIndx = 0
		colIndx = 0
		foreach(inst data
			;;create TEG cv
			instName = nth(0 inst)
			cvName = strcat(cName "_RTEG1_" instName)
			tegcv = dbOpenCellViewByType(lName cvName "layout" "maskLayout" "w")
			printf("Creating RTEG %s to %s...\n" cvName lName)
		
			;;create res/mimc
			if(restype == "mimcap" then 
				clay = instlay 
				forIndx = 1
			else
				devTypeValue = nth(2 inst)
				if(devTypeValue == "series" then clay = instlay  else clay = instlaysh 	)	
				forIndx = 3
			);;if
		
			param = list()
			
			for(i forIndx length(inst)-1
				ele = nth(i inst)
				prompt = nth(i prompts)				
				valueType = cadar(setof(x prop rexMatchp( prompt car(x) ) ))
				;;convert modelID to int
				if(prompt == "ModelID" then ele = atoi(ele) valueType = "integer")
				if(prompt == "INFRA_ver" then sprintf(ele "%.1f" evalstring(ele)*1.0) )
				if(prompt == "Fab" then FabValue = ele)
				if(prompt == "SharpPts" then SharpPts = linereadstring(ele))
				if(prompt == "apang" then lsa = evalstring(ele))				
				;;convert any char not matchp "n/N" to TRUE, else, FALSE
				if(valueType == "boolean" then 
					if(ele != "" && !rexMatchp("^[N|n]" ele) then ele = "TRUE" else ele = "FALSE")
				);;if
				if(valueType == "string" then
					if(rexMatchp("^[Y|X|y|x]" ele) then ele = "Yes" 
					else 
						if(rexMatchp("^[N|n]" ele) then ele = "No")
					)
				);;if
				if(prompt == "aRel" then aRelValue = ele)
				if(prompt == "arlC" then arlCValue = ele)
				if(prompt == "vtbfc" && ele == "No" then ele = "")
				if(!valueType then valueType = "string")
				param = append1(param list(prompt valueType ele))	
				
				;;get ppd labels for res
				if(restype != "mimcap" then
					if(prompt == "A" then Area = ele)
					if(prompt == "ORaW" then ORaWValue = ele)
					if(prompt == "MRaW" then MRaWValue = ele)
					if(prompt == "ReW"  then ReWValue = ele)
					if(prompt == "ADR"  then ADRValue = ele)					
				else
					if(prompt == "l" then lValue = ele)
					if(prompt == "w" then wValue = ele)
					if(prompt == "c" then cValue = ele)	
					if(prompt == "cham" then chamValue = ele)	
				);;if					
			);;for	
			
			if(rexMatchp("^seriesm[0-9]" instType) || rexMatchp("^shuntm[0-9]" instType) then
				sla = rdsBawMeshGetLongSideAngle(SharpPts)		
				cla1 = 90.0-sla 
				cla2 = 270.0-sla 
			else
				if(rexMatchp("^seriesq[0-9]" instType) || rexMatchp("^shuntq[0-9]" instType) then
					sla = 90.0-lsa	
					cla1 = lsa
					cla2 = 180.0+lsa				
				);;if
			);;if
			
			if(restype != "mimcap" then
				sprintf(rotValue "%A" sla)
				claValue = strcat( sprintf(nil "%A" cla1) " " sprintf(nil "%A" cla2) )
				if(arlCValue != "" then 
					relAngList = list()
					arlCList = linereadstring(arlCValue)
					foreach(relAng arlCList relAngList = append1(relAngList sprintf(nil "%A" relAng+sla))  )
					arlCStr = buildString(relAngList)
				);;if
				param = append(param   list( list("cDir" "string" "No")  list("rot" "string" rotValue) list("cla" "string" claValue) )  )	
				tranRot = "R0"
			else
				rotValue = "0.0"
				FabValue = "OSK"
				ADRValue = t
				param = append(param   list( list("ToCalc" "string" "C")  	list("SV_thickness" "string" "400n")  
										list("rot" "string" rotValue)  		list("Term1_Top" "boolean" t) 
										list("Term1_Left" "string" "0.0")  	list("Term1_Right" "string" "0.0")  
										list("Term2_Lay" "string" "MTE")  	list("Term2_Len" "string" "14.5")  
										list("ModelID" "integer" 228) 		list("Infra_Ver" "string" "2.0")
										list("Fab" "string" "OSK")    		list("Process" "string" "2.1")
										list("Band" "string" "3 RX")	)  )
				tranRot = "R270"
			);;if		
			newInst = dbCreateParamInst(tegcv clay instName list(0 0) tranRot 1 param t )
			dbReplaceProp(newInst "Fab" "string" FabValue )
			;;if(aRelValue == "Yes" then dbReplaceProp(newInst "arlC" "string" arlCStr))
			if(restype == "quad" then dbReplaceProp(newInst "ADR" "boolean" ADRValue ) )
		
		
			;;create ppd_1port for highAR doe and ? for mimcap doe 
			if(restype != "mimcap"  then
				sprintf(Area "%.3f" evalstring(Area)/1000.0)
				Area = strcat(Area "K")			
/*				ppdExtraList = list( list("ResonatorType" "string" devTypeValue)  		list("AddLbl" "boolean" t)  
									list("lblT3" "string" strcat("A=" Area)) 			list("ADR" "boolean" ADRValue) 
									list("lblT1" "string" "MESH") 						list("lblB1" "string" strcat("ORaW=" ORaWValue)) 	
									list("lblB2" "string" strcat("ReW=" ReWValue)) 		list("tTle" "string" cvName) 
									list("lblB3" "string" strcat("MRaW=" MRaWValue))  	list("bTle" "string" upperCase(devTypeValue) )  	
								)			
*/
;;05/11/2023,updated ppd label for modeling team highAR DOE since each TEG size is 380 um only	
				ppdExtraList = list( list("ResonatorType" "string" devTypeValue)  		list("AddLbl" "boolean" t)  
									list("lblT3" "string" "") 							list("ADR" "boolean" ADRValue) 
									list("lblT1" "string" "") 							list("lblB1" "string" instName) 	
									list("lblB2" "string" Area) 						list("tTle" "string" "") 
									list("lblB3" "string" "")  							list("bTle" "string" "" )  	
								)					
			else
				ppdExtraList = list( list("ResonatorType" "string" "series")  			list("AddLbl" "boolean" t)  
									list("lblT3" "string" strcat("C=" cValue)) 			list("ADR" "boolean" t) 
									list("lblT1" "string" "CAP") 						list("lblB1" "string" strcat("W=" wValue)) 	
									list("lblB2" "string" strcat("L=" lValue)) 			list("tTle" "string" cvName) 
									list("lblB3" "string" strcat("CHAF=" chamValue) )	list("bTle" "string" "" )  	
								)		

			);;if
			ppdParms = append(ppdparmlist ppdExtraList)				
			ppdDst = dbCreateParamInst(tegcv ppdlay nil ppdCoord "R0" 1 ppdParms t) 
			
						
			;;create vtb and 5 um rectangle
			if(ADRValue == "TRUE" then
				vtbL = vtbLenADR
			else
				vtbL = vtbLenPOR
			);;if
			vtbParms = append(vtbparmlist list( list("lenHor" "float" vtbL)  list("ADR" "boolean" ADRValue) )  )
			vtbDst = dbCreateParamInst(tegcv vtblay nil list(vtbCoordX vtbCoordY) "R0" 1 vtbParms t) 
			MTERect = dbCreateRect(tegcv "BAW_MTE" rectbbx)

		
			;;move resonator/mimcap to the right spot	
			;;resonator is 15 um away from vtb MTE right edge
			if(restype == "highARRes" || restype == "quad" then
				instY = cadr(centerBox(rectbbx))
				instbbx = newInst~>bBox
				instdx = 10.0
				;;instX = rightEdge(rectbbx)+instdx+0.5*(rightEdge(instbbx)-leftEdge(instbbx))
				;;resonator is not 100% symmetric on its center, so use left edge instead
				instX = rightEdge(rectbbx)+instdx-leftEdge(instbbx)
				newInst = dbMoveFig(newInst tegcv list(instX:instY "R0") )	
			else
				mteEncPzl = 5.0
				instY = cadr(centerBox(rectbbx))
				instbbx = newInst~>bBox
				instdx = 25.0
				;;move mimcap 25 um away from signal pad
				instX = rightEdge(rectbbx)+instdx-leftEdge(instbbx)-mteEncPzl
				newInst = dbMoveFig(newInst tegcv list(instX:instY "R0") )	
					
			);;if
			
			
			;;create frame/padbe
			if(frMB2Chk then	
				foreach(pb padbes dbCopyFig(pb tegcv list(0:0 "R0" 1) ) )	
				frame = dbCopyFig(car(frms) tegcv list(0:0 "R0" 1) )
				;;update frame settings
				trimlist = list( list("TEG" "boolean" t) )
				if(devTypeValue == "series" then 
					trimlist = append(trimlist list( list("TFS" "string" "Transparent") list("TFP" "string" "Fully_Covered") ) )
				else
					trimlist = append(trimlist list( list("TFP" "string" "Transparent") list("TFS" "string" "Fully_Covered") ) )
				);;if
				/*for(i 1 6				
					trim = strcat("MF" sprintf(nil "%d" i))
					trimlist = append1(trimlist list(trim "string" "Transparent"))
					trim = strcat("TF" sprintf(nil "%d" i))
					if(i == 1 then
						trimlist = append1(trimlist list(trim "string" "Transparent"))
					else
						trimlist = append1(trimlist list(trim "string" "Fully_Covered"))
					);;if
				);;for
				*/
				dbReplacePropList(frame trimlist)	
				
			);;if
	
			
/*			
			;;rotate resonator due to cutline angle: 
			;;minAng > 90 rot = 90-minAng, maxAng < 270 rot = 270 - maxAng 
			;;clas = linereadstring(newInst~>cla)
			minCla = apply('min linereadstring(newInst~>cla) )
			maxCla = apply('max linereadstring(newInst~>cla) )
			if(minCla > 90.0 then 
				rotA = sprintf(nil "%A" 90-minCla) newInst~>rot = rotA
			else
				if(maxCla < 270.0 then
					rotA = sprintf(nil "%A" 270-maxCla) newInst~>rot = rotA
				);;if
			);;if
			
*/			

			if(restype != "mimcap"  then
				;;create MTE connection	for resonators		
				connPolys = rdsBawResonatorTEGConnection(ppdTmp newInst  MTERect ppdTop ppdBot ppdLeft ppdRight TEGWidValue ppdCoord ADRValue )
				
			else
				;;mimcap is 5 um rect + 25 um trapodize on MTE, rectangle on MBE side
				connPolys = rdsBawMimcapTEGConnection(ppdTmp newInst  MTERect ppdTop ppdBot ppdLeft ppdRight TEGWidValue ppdCoord ADRValue )
														
			
			);;if
			
		
			;;create connections			
			mteConn = nth(0 connPolys)
			dbCreatePolygon(tegcv "BAW_MTE" mteConn)
			mbeConn = nth(1 connPolys)
			dbCreatePolygon(tegcv "BAW_MBE" mbeConn)
				
				
			res = setof(x tegcv~>instances rexMatchp("^mimcap" x~>cellName) || rexMatchp("^series" x~>cellName) || rexMatchp("^shunt" x~>cellName) || 
											rexMatchp("^vtb" x~>cellName)|| x~>cellName == "ppd_1port" ||  x~>cellName == "ppd")
			shps = setof(x tegcv~>shapes x~>layerName == "BAW_MTE" || x~>layerName == "BAW_MBE")
			resConnList = nconc(res shps)
			rdsBawXmlConnectLayers(tegcv resConnList nil)

			dbSave(tegcv)
			
			
			;;copy tegcv to top cv
			;;dbCopyFig(tegcv topcv list(colIndx*cellW: rowIndx*cellL "R0" 1) )
			dbCreateInst(topcv tegcv nil list(colIndx*cellW  rowIndx*cellL) "R0" 1)
			if(colIndx < num-1 then colIndx += 1 else colIndx = 0 rowIndx += 1)
			dbClose(tegcv)
		);;foreach
	
		
		dbClose(ppdTmp)
		dbSave(topcv)
		dbClose(topcv)
		dbClose(instlay)
		dbClose(ppdlay)
		dbClose(vtblay)
		if(restype == "highARRes" || restype == "quad" then dbClose(instlaysh))
		printf("\nTEG program is done.\n") 
		if(frMB2Chk then 
			dbClose(bkcv)
			tmp1 = ddGetObj(lName varName) if(tmp1 then ddDeleteObj(tmp1))
		);;if
		tmp2 = ddGetObj(lName ppdVar)  if(tmp2 then ddDeleteObj(tmp2)) 
	);;prog
);;proc




procedure(rdsBawMeshGetLongSideAngle(pts)
	prog( (Npts lse lspts i p1 p2 p1p2 ang sla Rpts pt p1rot p1rotx piAdd)
		;;find longest edge
		Npts = append1(pts car(pts))
		lse = 0.0
		lspts = list(nth(0 Npts) nth(1 Npts)) 
		for(i 0 length(Npts)-2
			p1 = nth(i Npts)
			p2 = nth(i+1 Npts)
			p1p2 = dist(p1 p2)
			if(p1p2 > lse then 
				lse = p1p2
				lspts = list(p1 p2)
			)		
		);;for
		
		;;get long side points lspts
		;;now find its angle, if <0 ang += 180.
		;;for each pt, rotate 90-ang
		p1 = car(lspts)
		p2 = cadr(lspts)
		if(car(p1)== car(p2) then
			ang = 90.0
		else
			ang = atan( (cadr(p1)-cadr(p2))/(car(p1)-car(p2)) )
			ang = ang*180.0/2.0/acos(0.0)
			if(ang < 0 then ang += 180.0)
		);;if

		sla = 90.0-ang

		Rpts = list()
		foreach(pt pts
	    	Rpts = append1( Rpts rdsRotatePoint( pt  sla ) )
		);;foreach
		
		;;if any ptx< lspts x, then sla += 180.0
		p1rot = rdsRotatePoint(p1 sla)
		p1rotx= car(p1rot)
		piAdd = nil
		foreach(pt Rpts
			if(car(pt)< p1rotx then piAdd = t)
		);;foreach
		
		if(piAdd then sla += 180.0)
		
		return(sla)
	);;prog
);;proc



procedure(rdsBawResonatorTEGConnection(tmpcv resInst  MTERect ppdTop ppdBot ppdLeft ppdRight TEGWidValue ppdCoord ADRValue)
	prog( (ppdBarWid ppddx mbedy instTmp instTran instbbx mteclr mbeclr mteAA instCntr mteAANew mteAANewPts mteclrPts
			newele mteclrOut pt mteclrSizeDn mteclrPts mteclrInnerPts mteclrOut  rectbbx vtbuporgn vtbdnorgn mteup mtedn 
			mteRectDx mteupFinal mtednFinal mteupFinalX	mteupFinal mtednFinal mteRectLineUp 
			mteRectLineDn crsup crsdn mteupFinal mteRectLineUp mteRectLineDn mteConn mteAA mbeClrPtsList mbeLines i line crs
			mbeLine1 mbeLine2 mbeLineUp mbeLineDn mbeLineUpPt1 mbeLineDnPt1 mbeupout mbeupin mbednout mbednin 
			outlist mbeupPt lup l1 crsup  mbednPt ldn crsdn mbednPt mteAACntrLine p1 p2 l1 top2 top1 
			topDn mbeUp mbeDn botDn bot1 bot2 pt1 pt2 pt3 pt4 pt5 pb5 pb4 pb3 pb2 pb1 mbeConn shp) 
		if(ADRValue == "TRUE" then mbedx = 100.0 else mbedx = 100.0)
		ppdBarWid = 32.0
		ppddx = 200.0
		mbedy = 20.0
		instTmp = dbCopyFig(resInst tmpcv  list(0:0 "R0" 1))
		instTran = instTmp~>transform
		instbbx = instTmp~>bBox
		dbFlattenInst(instTmp 1 t)
		mteclr = setof(x tmpcv~>shapes rexMatchp("BAW_MTE" x->layerName) && ( x~>prop~>name == list("BAW_SERIES_MTE_COLLAR") || x~>prop~>name == list("BAW_SHUNT_MTE_COLLAR")   )) 
		mbeclr = setof(x tmpcv~>shapes rexMatchp("BAW_MBE" x->layerName) && ( member("BAW_SERIES_MBE_COLLAR" x~>prop~>name)  || member("BAW_SHUNT_MBE_COLLAR" x~>prop~>name)   ))               
		mteAA  = setof(x tmpcv~>shapes rexMatchp("BAW_MTE" x->layerName) && rexMatchp("polygon" x~>objType) && !x~>prop    )
		instCntr = centerBox(car(mteAA)~>bBox)
		
		
		;;get mte/mbe collar outer points
	    mteAANew = dbLayerSize(tmpcv "BAW_NoTF1" mteAA 3.0 1024)
	    mteAANewPts = car(mteAANew)~>points
	    
	    mteclrPts = list()
	    newele = dbLayerSize(tmpcv "BAW_NoTF1" mteclr -1.0 1024)
		if( length(newele)>1 then 
        	mteclrPts = apply('nconc newele~>points)
    	else
        	mteclrPts = car(newele)~>points
    	)
		mteclrOut = list()  
    	foreach(pt mteclrPts  
        	if(!rdsBawSkinnyPointInPolygon(pt mteAANewPts) && !rdsBawPointOnBoundary(pt mteAANewPts) then	 
        		mteclrOut = append1(mteclrOut pt) )         
    	);;foreach
    	mteclrSizeDn = car(newele)
    	
    	
    	mbeclrPts = list()
    	mbeclrInnerPts = list()
    	;;newele = dbLayerSize(tmpcv "BAW_NoTF1" mbeclr -1.0 1024)
    	newele = setof(x tmpcv~>shapes rexMatchp("BAW_MBE" x->layerName) && ( member("BAW_SERIES_MBE_COLLAR" x~>prop~>name)  || member("BAW_SHUNT_MBE_COLLAR" x~>prop~>name)   ))  
    	if( length(newele)>1 then 
        	mbeclrPts = apply('nconc newele~>points)
    	else
        	mbeclrPts = car(newele)~>points
    	)
		mbeclrOut = list()  
    	foreach(pt mbeclrPts  
        	if(!rdsBawSkinnyPointInPolygon(pt car(mteAA)~>points) && !rdsBawPointOnBoundary(pt car(mteAA)~>points) then	 
        		mbeclrOut = append1(mbeclrOut pt) 
        	else
        		mbeclrInnerPts = append1(mbeclrInnerPts pt)
        	)         
    	);;foreach
    	;;mbeclrSizeDn = car(newele)
    	
    	
    	;;find min/max slope from MTE rectangle top/bottom point to MTE outer collar points
    	rectbbx = MTERect~>bBox
    	vtbuporgn = cadr(rectbbx) 
    	vtbdnorgn = list( caadr(rectbbx)  cadar(rectbbx)  )
		mteup = rdsBawFindMinMaxSlope2(vtbuporgn  mteclrOut  "max")
    	mtedn = rdsBawFindMinMaxSlope2(vtbdnorgn  mteclrOut  "min")    	
    	

    	
    	;;compare mte min/max shape and mte rectangle (10 um) shape
    	;;if mteupY> mteRectUpy then use mteRectUpy, else use mteupY
    	;;if mtednY < mteRectDnY then use mteRectDnY, else use mtednY
    	
    	mteRectDx = 23.0
    	if(cadr(mteup) > topEdge(rectbbx) then   		
    		mteupFinal = list(rightEdge(rectbbx)+mteRectDx topEdge(rectbbx) )   		
    	else
    		mteupFinal = mteup
    	);;if
    	
    	if(cadr(mtedn) < bottomEdge(rectbbx) then    		
    		mtednFinal = list(rightEdge(rectbbx)+mteRectDx bottomEdge(rectbbx))
    	else
    		mtednFinal = mtedn
    	);;if
    	
    	if(cadr(mteup) > topEdge(rectbbx) || cadr(mtedn) < bottomEdge(rectbbx) then
    		mteupFinalX = rightEdge(rectbbx)+mteRectDx
    		mteupFinal = list(mteupFinalX topEdge(rectbbx) )
    		mtednFinal = list(mteupFinalX bottomEdge(rectbbx))
    		mteRectLineUp = list(vtbuporgn  mteupFinal)
    		mteRectLineDn = list(vtbdnorgn  mtednFinal)
    		crsup = rdsBawFindPolygonIntersectionPoints2(mteclrSizeDn mteRectLineUp)
    		crsdn = rdsBawFindPolygonIntersectionPoints2(mteclrSizeDn mteRectLineDn)
    		while( (!crsup || !crsdn ) && mteupFinalX < ppdRight+TEGWidValue
    			mteupFinalX += 1.0
    			mteupFinal = list(mteupFinalX topEdge(rectbbx) )
    			mtednFinal = list(mteupFinalX bottomEdge(rectbbx))
    			mteRectLineUp = list(vtbuporgn  mteupFinal)
    			mteRectLineDn = list(vtbdnorgn  mtednFinal)
    			crsup = rdsBawFindPolygonIntersectionPoints2(mteclrSizeDn mteRectLineUp)
    			crsdn = rdsBawFindPolygonIntersectionPoints2(mteclrSizeDn mteRectLineDn)
    		);;while
    		
    	);;if
    	
		;;mteConn = list(vtbdnorgn  vtbuporgn   mteup mtedn)
		mteConn = list(vtbdnorgn  vtbuporgn   mteupFinal mtednFinal)
		
		
		
		;;create MBE connection
		;;find MBE collar line points outside of AA
		;;mbeClrLinePts = apply('nconc dbFindProp(car(mbeclr)) "MBE_Collar_Points")~>value)
		;;mbeClrLinePts = foreach(mapcar pt mbeClrLinePts dbTransformPoint( pt instTran) )
		mteAA  = setof(x tmpcv~>shapes rexMatchp("BAW_MTE" x->layerName) && rexMatchp("polygon" x~>objType) && !x~>prop    )
		mbeClrPtsList = append1(car(mbeclr)~>points car(car(mbeclr)~>points))
		mbeLines = list()
		for(i 0 length(mbeClrPtsList)-2
			line = list(  nth(i mbeClrPtsList)  nth(i+1 mbeClrPtsList) )
			crs = rdsBawFindPolygonIntersectionPoints(car(mteAA) line)
			if(crs then 
				mbeLines = append1(mbeLines line)
			)
		);;for
				
	
		;;compare two mbe lines center y to get up/dn mbe lines
		;;get outter points of mbe line up/dn
		mbeLine1 = nth(0 mbeLines)
		mbeLine2 = nth(1 mbeLines)

	
		if(cadr(centerBox(mbeLine1)) > cadr(centerBox(mbeLine2)) then 
			mbeLineUp = mbeLine1
			mbeLineDn = mbeLine2
		else
			mbeLineUp = mbeLine2
			mbeLineDn = mbeLine1
		);;if
		mbeLineUpPt1 = car(mbeLineUp)
		mbeLineDnPt1 = car(mbeLineDn)
		if(!rdsBawSkinnyPointInPolygon(mbeLineUpPt1 car(mteAA)~>points) && !rdsBawPointOnBoundary(mbeLineUpPt1 car(mteAA)~>points) then
			mbeupout = nth(0 mbeLineUp)
			mbeupin = nth(1 mbeLineUp)
		else
			mbeupout = nth(1 mbeLineUp)
			mbeupin = nth(0 mbeLineUp)
		)
		if(!rdsBawSkinnyPointInPolygon(mbeLineDnPt1 car(mteAA)~>points) && !rdsBawPointOnBoundary(mbeLineDnPt1 car(mteAA)~>points) then
			mbednout = nth(0 mbeLineDn)
			mbednin = nth(1 mbeLineDn)
		else
			mbednout = nth(1 mbeLineDn)
			mbednin = nth(0 mbeLineDn)
		)
		
		
		;;compare mbe up/dn points,find pt with max x
		outlist = append1(mbeclrOut car(mbeclrOut))
		if(car(mbeupout)>= car(mbeupin) then
			mbeupPt = mbeupout
		else
			lup = list(mbeupin  car(mbeupin):cadr(mbeupin)+20000.0)
			for(i 0 length(outlist)-2
				l1 = list( nth(i outlist) nth(i+1 outlist) )
				crsup = rdsBawFindLineIntersectionPoints(lup l1)
				if(crsup then mbeupPt = crsup)
			);;for
			if(!mbeupPt then mbeupPt = mbeupin )
		);;if
		
		if(car(mbednout)>= car(mbednin) then
			mbednPt = mbednout
		else
			ldn = list(mbednin  car(mbednin):cadr(mbednin)-20000.0)			
			for(i 0 length(outlist)-2
				l1 = list( nth(i outlist) nth(i+1 outlist) )
				crsdn = rdsBawFindLineIntersectionPoints(ldn l1)
				if(crsdn then mbednPt = crsdn )
			);;for
			if(!mbednPt then mbednPt = mbednin )
		);;if


/*		;;this doesn't work well for some case the connection cros the collar edge line	
		;;use max x points to create up/dn circles with r=2
		;;find crossing points between mbe collar outer points and the circle
		cirup = rdsBawCreateCircle(tmpcv  "MSK_CM1"  mbeupPt  2.0  20) 	
		cirdn = rdsBawCreateCircle(tmpcv  "MSK_CM1"  mbednPt  2.0  20) 	

		cirupCrs = nil
		foreach(pt mbeclrOut if(rdsBawPointOnBoundary(pt cirup~>points) then cirupCrs = pt))
		if(!cirupCrs then
			mbeclrOutPtsList = append1(mbeclrOut car(mbeclrOut) )
			for(i 0 length(mbeclrOutPtsList)-2
				p1 = nth(i mbeclrOutPtsList)
				p2 = nth(i+1 mbeclrOutPtsList)
				l1 = list(p1 p2)
				zz = rdsBawFindPolygonIntersectionPoints2(cirup l1)
				if(zz then cirupCrs = caar(zz))
			);;for
		);;if
		
		cirdnCrs = nil
		foreach(pt mbeclrOut if(rdsBawPointOnBoundary(pt cirdn~>points) then cirdnCrs = pt))
		if(!cirdnCrs then
			mbeclrOutPtsList = append1(mbeclrOut car(mbeclrOut) )
			for(i 0 length(mbeclrOutPtsList)-2
				p1 = nth(i mbeclrOutPtsList)
				p2 = nth(i+1 mbeclrOutPtsList)
				l1 = list(p1 p2)
				zz = rdsBawFindPolygonIntersectionPoints2(cirdn l1)
				if(zz then cirdnCrs = caar(zz))
			);;for
		);;if
*/		

		;;find mbeclrInnerPts center (intersection between mteAA centerbox line and mbeclrInnerPts line)
		mteAACntrLine = list( list(0.0  cadr(centerBox(car(mteAA)~>bBox))) list(20000.0 cadr(centerBox(car(mteAA)~>bBox)))  )
		for(i 0 length(mbeclrInnerPts)-2
			p1 = nth(i mbeclrInnerPts)
			p2 = nth(i+1 mbeclrInnerPts)
			l1 = list(p1 p2)
			crs =rdsBawFindLineIntersectionPoints(l1 mteAACntrLine) 
			if(crs then  mbeclrInnerCntr = centerBox(l1)  )				
		);;for
		
		;;create polygon from ppd top bar + 100 um->go straight down by 20 um->connect mbe up ->mbe inner collar center ->mbe dn ->go straight down till 20 to bottom bar->ppd bot bar
		;; if up/dn X > ppd right edge + 20 || up/dn Y is higher than top/bot pad bot/top edge, then extend connection from ppd right edge 
		top2  = list( car(ppdCoord)+TEGWidValue  ppdTop)
		top1  = list( rightEdge(rectbbx)+mbedx  ppdTop)
		topDn = list( rightEdge(rectbbx)+mbedx  ppdTop-ppdBarWid-mbedy )
		mbeUp = mbeupPt
		mbeDn = mbednPt
		botDn = list( rightEdge(rectbbx)+mbedx  ppdBot+ppdBarWid+mbedy )
		bot1  = list( rightEdge(rectbbx)+mbedx    ppdBot )
		bot2  = list( car(ppdCoord)+TEGWidValue    ppdBot )
		
		if(car(mbeUp)>ppdRight+20 || car(mbeDn)>ppdRight+20 || cadr(mbeUp) > ppdTop-80.0 || cadr(mbeDn)< ppdBot+80.0 then
			pt1 = list(ppdRight+50.0  	ppdTop)
			pt2 = list(ppdRight-20  			ppdTop)
			pt3 = list(ppdRight-20  			ppdTop-ppdBarWid)
			pt4 = list(ppdRight+50.0  	ppdTop-ppdBarWid)
			pt5 = list(ppdRight+50.0  	ppdTop-ppdBarWid-mbedy)
			
			pb5 = list(ppdRight+50.0  	ppdBot)
			pb4 = list(ppdRight-20  			ppdBot)
			pb3 = list(ppdRight-20  			ppdBot+ppdBarWid)
			pb2 = list(ppdRight+50.0  	ppdBot+ppdBarWid)
			pb1 = list(ppdRight+50.0  	ppdBot+ppdBarWid+mbedy)
			
			mbeConn = list(top2 pt1 pt2 pt3 pt4 pt5 mbeUp mbeDn pb1 pb2 pb3 pb4 pb5 bot2)
		else
			mbeConn = list(top2 top1 topDn mbeUp mbeclrInnerCntr mbeDn botDn bot1 bot2)
		);;if
		

	
		;;clean up all shapes
		foreach(shp tmpcv~>shapes dbDeleteObject(shp))
		
		return(list(mteConn mbeConn))
		
	);;prog
);;proc




procedure(rdsBawMimcapTEGConnection(tmpcv capInst  MTERect ppdTop ppdBot ppdLeft ppdRight TEGWidValue ppdCoord ADRValue)
	prog( (ppdBarWid ppddx mbedy mtedx shp inst instTmp instTran instbbx mteShp mbeShp pzlShp h2Shp capAApre capAA
			obj mtebbx rectbbx vtbuporgn vtbdnorgn instntr mteConn mbeRight mbeR mbeL mbeConn errmsg shp) 
		if(ADRValue == "TRUE" then mbedx = 100.0 else mbedx = 100.0)
		ppdBarWid = 32.0
		ppddx = 200.0
		mbedy = 20.0
		mtedx = 5.0
		foreach(shp tmpcv~>shapes dbDeleteObject(shp))
		foreach(inst tmpcv~>instances dbDeleteObject(inst))
		instTmp = dbCopyFig(capInst tmpcv  list(0:0 "R0" 1))
		instTran = instTmp~>transform
		instbbx = instTmp~>bBox
		
		dbFlattenInst(instTmp 1 t)
		mteShp = setof(x tmpcv~>shapes rexMatchp("BAW_MTE" x->layerName) )
		mbeShp = setof(x tmpcv~>shapes rexMatchp("BAW_MBE" x->layerName) )  
		m1Shp = setof(x tmpcv~>shapes rexMatchp("BAW_M1" x->layerName) )          
		pzlShp = setof(x tmpcv~>shapes rexMatchp("BAW_PZL" x->layerName) )   
		h2Shp = setof(x tmpcv~>shapes rexMatchp("BAW_H2" x->layerName) )       
		capAApre = dbLayerAnd(tmpcv "MSK_CM1" mbeShp h2Shp)
		capAA = dbLayerAndNot(tmpcv "MSK_CZM" capAApre pzlShp)
		foreach(obj capAApre dbDeleteObject(obj))
		
		;;MTE connection
		mtebbx = car(mteShp)~>bBox
		rectbbx = MTERect~>bBox
    	vtbuporgn = cadr(rectbbx) 
    	vtbdnorgn = list( caadr(rectbbx)  cadar(rectbbx)  )
		
		instCntr = centerBox(car(capAA)~>bBox)
		
		mteConn = list(vtbuporgn  list(leftEdge(mtebbx)-mtedx  topEdge(mtebbx))   list(leftEdge(mtebbx)  topEdge(mtebbx)) 
						list(leftEdge(mtebbx)  bottomEdge(mtebbx))  list(leftEdge(mtebbx)-mtedx  bottomEdge(mtebbx))  vtbdnorgn  )
		
		
		
		
		;;create MBE connection
		;; if up/dn X > ppd right edge + 20 || up/dn Y is higher than top/bot pad bot/top edge, then extend connection from ppd right edge 
		mbeRight = rightEdge(car(mbeShp)~>bBox)
		mbeR = car(ppdCoord)+TEGWidValue
		mbeL = mbeRight
		if(mbeRight < ppdRight then			
			mbeConn = list(mbeL:ppdBot mbeL:ppdTop mbeR:ppdTop mbeR:ppdBot)
		else
			unless(mbeL <= mbeR then 
				errmsg = "TEG width < mimcap width.\nPlease reset your \"RTEG Overall Width\" in the GUI.\n "
				rdsBasePopupError(errmsg)
				return(nil)
			);;unless
			mbeConn = list(mbeL: (ppdTop-ppdBarWid)  ppdRight: (ppdTop-ppdBarWid)  ppdRight:ppdTop mbeR:ppdTop
							mbeR:ppdBot  ppdRight:ppdBot   ppdRight: (ppdBot+ppdBarWid)  mbeL:(ppdBot+ppdBarWid))
		);;if
		
			
		;;clean up all shapes
		foreach(shp tmpcv~>shapes dbDeleteObject(shp))
		
		
		return(list(mteConn mbeConn))
	);;prog
);;proc
