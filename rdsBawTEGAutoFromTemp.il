procedure( rdsBawTEGAutoFromTempGUI()
	prog( (cv lcell libNames defaultLibName defaultCellName defaultViewName cellNames viewNames toplbl
			lName cNamelbl cName runlbl runList cNameAdd addtxt cNameRemove removetxt emplbl 
			fields bawTEGAutoForm form runChk)
        cv = geGetEditCellView()
        ;;libNames = sort(setof(z ddGetLibList()~>name !pcreMatchp("/rds" ddGetObj(z)~>readPath) ) 'alphalessp)
        lcell = setof(z ddGetLibList() !pcreMatchp("/rds" z~>readPath) )
        libNames = sort(lcell~>name 'alphalessp)


        if(cv then
            defaultLibName  = cv~>libName
	        defaultCellName = cv~>cellName
	        defaultViewName = cv~>viewName
        else
	        defaultLibName  = car(reverse(libNames))
	        defaultCellName = car(ddGetObj(defaultLibName)~>cells)~>name
	        defaultViewName = car(ddGetObj(defaultLibName defaultCellName)~>views)~>name			
        )

        cellNames = sort(ddGetObj(defaultLibName)~>cells~>name 'alphalessp)                	
        viewNames = ddGetObj(defaultLibName defaultCellName)~>views~>name    
           
           
		toplbl = hiCreateLabel( ?name 'toplbl
								?labelText "Please select TEGs:" 
								)	         
        lName = hiCreateCyclicField(  	?name           'lName
		             			        ?prompt         "Library:"
		             			        ?choices          libNames
		             			        ?value          defaultLibName                 
				                        ?callback	(lambda (field scope value )
						                            scope->cName->choices = sort(setof(z ddGetObj(value)~>cells~>name ddGetObj(value z "layout")
					                            								&& length(parseString(z "_")) == 3  
		                                                                        && rexMatchp( "[0-9][0-9]$"  car(last(parseString(z "_"))) ) 
					                            								 ) 'alphalessp)   					                                             
						                            scope->runList->value = nil
						                            scope->runList->choices = nil
						                            )      
                                    )                                     
        
		cNamelbl = hiCreateLabel( ?name 'cNamelbl
								?labelText "Cells:" 
									)
        cName = hiCreateListBoxField(?name           'cName
             			             ?prompt         ""
		                            ?multipleSelect t
		                            ?changeCB	"rdsFrameVarcNameCB()"
		                            ?choices 	sort(setof(z ddGetObj(defaultLibName)~>cells~>name ddGetObj(defaultLibName z "layout") 
                            							&& length(parseString(z "_")) == 3  
		                                                && rexMatchp( "[0-9][0-9]$"  car(last(parseString(z "_"))) )  
                            							 ) 'alphalessp)                    
		                            )
	                            
        runlbl = hiCreateLabel( ?name 'runlbl
								?labelText "Cell List:"
								)
        runList = hiCreateListBoxField(?name           'runList
             			                ?prompt         ""
	                                    ?changeCB	"rdsFrameVarRunListCB()"
	                                    ?multipleSelect t
		                            	?choices 	sort(setof(z ddGetObj(defaultLibName)~>cells~>name ddGetObj(defaultLibName z "layout") 
                            							&& length(parseString(z "_")) == 3  
		                                                && rexMatchp( "[0-9][0-9]$"  car(last(parseString(z "_"))) )  
                            							 ) 'alphalessp)           
                                    )
	                            
        cNameAdd = hiCreateButton(?name 		'cNameAdd
	                               ;; ?buttonText 	"Add Selected Cells to Cell List "
	                                ?buttonText 	"Add"
	                                ?buttonIcon   hiLoadIconFile("right-blue.png" 48 48)
	                                ?callback 	"rdsFrameVarAddSelectedCB()"
	                                ?enabled 	nil
	                                ?showTextWithIcon  t
	                            )

        addtxt = hiCreateLabel( ?name 'addtxt
								?labelText "Add"
										)
        cNameRemove = hiCreateButton( ?name 		'cNameRemove
	                               ;; ?buttonText 	"Remove Selected from Cell List"
	                                ?buttonText 	"Remove"
	                                ?buttonIcon     hiLoadIconFile("left-blue.png" 48 48)
	                                ?callback 	"rdsFrameVarRemoveSelectedCB()"
	                                ?enabled 	nil
	                                ?showTextWithIcon  t
	                            ) 
	    removetxt = hiCreateLabel( ?name 'removetxt
								?labelText "Remove"
										)    
		emplbl = hiCreateLabel( ?name 'emplbl
								?labelText " " 
								)								                            								                                               		                             
        fields = list(
                      list(toplbl  20:10 600:30 200 )   
                      list(lName  20:40 700:30 80 )
                      list(cNamelbl  20:70 400:30 80 ) 
			          list(cName  20:90 500:300 80 ) 
			          list(runlbl 620:70 500:30 80 ) 
			          list(runList 620:90 500:300 100 ) 
		              list(cNameAdd 550:140 150:30) 
			          list(cNameRemove 550:180 150:30)  
			          list(emplbl 580:400 580:20 250 )                                           			
                      )                                                 

        bawTEGAutoForm = hiCreateAppForm( ?name 'bawTEGAutoForm
                                       ?formTitle "Crate 1-port RTEGs for Resonators from All Selected Variants Using Template... "
                                       ?fields     fields    
                                       ?initialSize t
                                       ;;?initialSize  1800:600
                                       ?callback "form = hiGetCurrentForm() 
                                                   runChk = rdsBawTEGAutoFromTempCB(form) 
                                                   if( runChk then hiFormCancel(bawTEGAutoForm))"
                                       ?buttonLayout  '(Empty  (Generate\ RTEGs hiFormApply) (Cancel hiFormCancel) )  
                                       )        

        hiDisplayForm('bawTEGAutoForm )
 	
	
	);;prog
);;proc



procedure( rdsBawTEGAutoFromTempCB(form)
	prog( (cells lN vN libId libPath cid mydate cshFile tegTmp errmsg vartb jm4tb jm4tbchk celltb varList 
			jm4varList totvarlist splits_tb infra35_tb infra35Res_tb  cell insts reslist varList jm4series resName
			meshlist resName jm4rest jm4pre pre prelist s1s p1s seSets shSets s1sNames s1sVars p1sNames p1sVars
			seResNames shResNames jm4varList dstCellList techLib s3lay sh3lay vtbxylist prjstrs prj1 prj2 cocmd
			Infra35ResListOrg Infra35ResList Infra35ResName resName dstCellList techLib cplist ncv 
			splitName splitPattern split_res_list ppName ppcv ints vtbxylist vtbs polys ppints ppd 		)
	
		cells = form->runList->choices 
        lN = form->lName->value
        vN = "layout"
        libId = ddGetObj(lN)
        libPath = libId~>readPath
        
        ;;extratct RTEG template
        tegTmp = car(setof(x ddGetObj(lN)~>cells~>name rexMatchp("_RTEG1_template" x))  )
        unless(tegTmp
        	errmsg = "No \"_RTEG1_template\" in Current Library. "
        	rdsBasePopupError(errmsg)			
        	return(nil)
        );;unless
        
        
        ;;create csh file as /tmp/user_date.csh
        cid = ipcBeginProcess("date +'%d%m%y'")
		mydate = ipcReadProcess(cid 2)
		mydate = car(parseString(mydate "\n"))
        cshFile = strcat("/tmp/" env(USER) "_" mydate ".csh")
               
        ;;check out for SOS prjs and when opened cv is under managed lib
        if(isFileName(strcat(env("PROJ_ROOT") "/" getShellEnvVar("PROJ_ID") "/cds_master/latest")) && lN == strcat(env(PROJ_ID) "_work") then
        	prjstrs = parseString(env(PROJ_ID) "_")
        	prj1 = nth(0 prjstrs)
        	prj2 = nth(1 prjstrs)
        	cocmd = strcat("soscmd co -vk2 -sr  " env(PROJ_ID) "_work/" prj1 "_" prj2 "*")
        	system(cocmd)
        	println(strcat("SOS checking out all cells with name " prj1 "_" prj2 ) )
        );;if
        
        ;;extract all resonators
        vartb = makeTable('vartb list())
        jm4tb = makeTable('jm4tb list())
        jm4tbchk = makeTable('jm4tbchk "")
        celltb = makeTable('celltb list())
        varList = list()
        jm4varList = list()
        totvarList = list()
        splits_tb = makeTable('splits_tb list())
        infra35_tb = makeTable('infra35_tb list())
        infra35Res_tb = makeTable('infra35Res_tb list())

        foreach(cell cells
        	cellId = dbOpenCellViewByType(lN cell vN)
        	ints = dbInstQuery(cellId cellId~>bBox)
			reslist=setof(aa ints atom(aa)&&(rexMatchp("^series" aa~>cellName)||rexMatchp("^shunt" aa~>cellName)|| rexMatchp("^rcap" aa~>cellName) ||rexMatchp("^mimcap" aa~>cellName)))	
			celltb[cell] = reslist			
			vartb[cell] = foreach(mapcar x reslist x~>name)
			varList = foreach(mapcar x vartb[cell] strcat(cell "_RTEG1_" x) )
			totvarList = append(totvarList varList) 
			
			;;if mesh/quad, get jm4 equavalent cells(series only), but eg. S1A/S1B/S1C/S1D will use S1A only
			meshlist=setof(aa reslist rexMatchp("^series[a-zA-Z]" aa~>cellName))
			if(meshlist then
				jm4tbchk[cell] = t
				jm4series = meshlist~>name
				;;resName = sort(jm4series 'alphalessp)
				resName = sort(jm4series 'alphalessp)
				jm4tb[cell] = setof(x resName !rexMatchp("[a-zA-Z]$" x))	;;get single ones	
				jm4rest = setof(x resName rexMatchp("[a-zA-Z]$" x))			;;splits/quads
				rexCompile("[a-zA-Z]$")
				jm4pre = foreach(mapcar x jm4rest rexReplace(x "" 1))
				jm4pre = removeListDuplicates(jm4pre)						
				foreach(pre jm4pre
					prelist = sort( setof(x jm4rest substring(x 1 length(x)-1) == pre) 'alphalessp)
					jm4tb[cell] = append1( jm4tb[cell] car(prelist))
				);;foreach
				;;jm4varList = foreach(mapcar x jm4tb[cell] strcat(cell "_RTEG1_" x "JM4") )
				;;totvarList = append(totvarList jm4varList) 
			else
				jm4tbchk[cell] = nil
			);;if
        	
        	
			;;do splits, grab all eg. S1A, S1B, S1C, S1D and name _RTEG1_S1
        	;; do this for S1, P1, Smax and Pmax
        	seSets = setof(x reslist rexMatchp("^series" x~>cellName))
        	shSets = setof(x reslist rexMatchp("^shunt" x~>cellName))
			
			;;semax = car(last(sort(seSets~>name 'alphalessp)) )
			;;shmax = car(last(sort(shSets~>name 'alphalessp)) )
			
			s1s = setof(x reslist rexMatchp("S1[A-Z]" x~>name))
			p1s = setof(x reslist rexMatchp("P1[A-Z]" x~>name))
			
			if(s1s then
				rexCompile("S1[A-Z].*")
				s1sNames = foreach(mapcar x s1s~>name rexReplace(x "" 0))
				s1sNames = removeListDuplicates(s1sNames)  
				s1sVars = foreach(mapcar x s1sNames strcat(cell "_RTEG1_" x "S1") )
				totvarList = append(totvarList s1sVars) 
				splits_tb[cell] = append(splits_tb[cell] s1sVars)
				
				;;get smax
				seResTb = makeTable('seResTb list())
				seMax = list()
				foreach(ele s1sNames
					seResTb[ele] = setof(x seSets rexMatchp(ele x~>name))
					seResCp = copy(seResTb[ele]~>name)
					seEleMax = car(last(sort(seResCp 'alphalessp)))
					if(rexMatchp( "[A-Z]" substring(seEleMax -1) ) then 
						seEleMax = substring(seEleMax 1 length(seEleMax)-1)
					);;if
					seMax = strcat(cell "_RTEG1_" seEleMax)
					totvarList = append1(totvarList seMax) 
					splits_tb[cell] = append1(splits_tb[cell] seMax)
				);;foreach
				splits_tb[cell] = removeListDuplicates(splits_tb[cell])	
			)
			
			if(p1s then
				rexCompile("P1[A-Z].*")
				p1sNames = foreach(mapcar x p1s~>name rexReplace(x "" 0))
				p1sNames = removeListDuplicates(p1sNames)  
				p1sVars = foreach(mapcar x p1sNames strcat(cell "_RTEG1_" x "P1") )
				totvarList = append(totvarList p1sVars) 
				splits_tb[cell] = append(splits_tb[cell] p1sVars)
				
				;;get pmax
				shResTb = makeTable('shResTb list())
				shMax = list()
				foreach(ele p1sNames
					shResTb[ele] = setof(x shSets rexMatchp(ele x~>name))
					shResCp = copy(shResTb[ele]~>name)
					shEleMax = car(last(sort(shResCp 'alphalessp)))
					if(rexMatchp( "[A-Z]" substring(shEleMax -1) ) then 
						shEleMax = substring(shEleMax 1 length(shEleMax)-1)
					);;if
					shMax = strcat(cell "_RTEG1_" shEleMax)
					totvarList = append1(totvarList shMax) 
					splits_tb[cell] = append1(splits_tb[cell] shMax)
				);;foreach
				splits_tb[cell] = removeListDuplicates(splits_tb[cell])		
			)
			
	
			;;do infra35
			infraResList = list()
			seResNames = seSets~>name
			shResNames = shSets~>name
			Infra35ResListOrg = append(seSets shSets)
			Infra35ResList = list()
			Infra35ResName = list()
			foreach(res Infra35ResListOrg
				resName = res->name
				;;for splits, do S/P[0-9]*A, else as S/P[0-9]*, just add
				if(pcreMatchp("(S|P)[0-9](.*)[A-Z]" resName) then   
					;;name = substring(resName 1 length(resName)-1)
					if(pcreMatchp("(S|P)[0-9](.*)A" resName) then
						Infra35ResName = append1(Infra35ResName resName)
						Infra35ResList = append1(Infra35ResList res)
					);;if
				else
					Infra35ResList = append1(Infra35ResList res)
					Infra35ResName = append1(Infra35ResName resName)
				);;if
			);;foreach
			Infra35TegName = foreach(mapcar x Infra35ResName strcat(cell "_RTEG1_" x "Infra35") )
			;;totvarList = append(totvarList Infra35TegName) 
			infra35_tb[cell] = Infra35TegName 
			infra35Res_tb[cell] = Infra35ResName 
        	dbClose(cellId)
        );;foreach
        
     
		;;run csh file to create all cells	
		dstCellList = rdsBawCopyCellsCshV2(cshFile libPath list(tegTmp) totvarList) 
 		
		
		;;update resonator/ppd/frame
		techLib = getShellEnvVar("RDS_CDS_TECH")	
        
        
		foreach(cell cells
			cellId = dbOpenCellViewByType(lN cell vN)
        	ints = dbInstQuery(cellId cellId~>bBox)
			;;reslist=setof(aa ints atom(aa)&&(rexMatchp("^series" aa~>cellName)||rexMatchp("^shunt" aa~>cellName) ||rexMatchp("^mimcap" aa~>cellName)|| rexMatchp("^rcap" aa~>cellName)))	
			cplist=setof(aa ints atom(aa)&&pcreMatchp("^series|^shunt|^mimcap|^vtb" aa~>cellName) )	
						
			
			;;reslist = celltb[cell]
			;;rdsBawTEGAutoUpdateTemp(cell lN reslist vartb "MESH" s3lay)
			;;rdsBawTEGAutoUpdateTemp(cell lN reslist vartb "MESH" "")
			rdsBawTEGAutoUpdateTemp(cell lN cplist vartb "MESH" "")
			
			/*if(jm4tbchk[cell] then
				s3lay = dbOpenCellViewByType(techLib "series3" vN)
				rdsBawTEGAutoUpdateTemp(cell lN reslist jm4tb "JM4" s3lay)
				dbClose(s3lay)
			);;if	
			*/		
			
 			
			;;do splits
			if(splits_tb[cell] then
				println("Creating RTEGs for splits...")
				foreach(split splits_tb[cell]  
					println(strcat("Updating cell " split "..."))
					ncv = dbOpenCellViewByType(lN split "layout" "maskLayout" "a")
					rexCompile(strcat(cell "_RTEG1_"))
					splitName = rexReplace(split "" 0)
					splitPattern = strcat(splitName "[A-Z].*")
					split_res_list = setof(x cplist rexMatchp(splitPattern x~>name))
					foreach(res split_res_list
						ppName = strcat(cell "_RTEG1_" res~>name)
						ppcv = dbOpenCellViewByType(lN ppName "layout" )
						ints = dbInstQuery(ppcv ppcv~>bBox)
						pplist=setof(aa ints atom(aa)&&pcreMatchp("^series|^shunt|^vtb" aa~>cellName) )	
						foreach(ele pplist dbCopyFig(ele ncv list(list(0 0) "R0" 1.0) ) )
						;;remove duplicate vtbs
						vtbxylist = list()
						vtbs = setof(x ncv~>instances rexMatchp("vtb" x~>cellName ))
						foreach(vtb vtbs if(!member(vtb~>xy vtbxylist) then vtbxylist = append1(vtbxylist vtb~>xy) else dbDeleteObject(vtb)))
						polys = setof(x ppcv~>shapes x~>layerName == "BAW_MBE" || x~>layerName == "BAW_MTE")
						foreach(ele polys dbCopyFig(ele ncv list(list(0 0) "R0" 1.0) ) )
						ppints = dbInstQuery(ppcv ppcv~>bBox)
						ppd = car(setof(x ppints atom(x)&& x~>cellName == "ppd_1port" ))
						lblB1 = ppd->lblB1
						lblB2 = ppd->lblB2
						tTle = ppd->tTle
						bTle = ppd->bTle
						dbClose(ppcv)
					);;foreach
					
					;;update ppd labels
					frameList = bawHierarchyFrame(ncv 1.0 nil)
					frame = nth(2 frameList)
					frameW = evalstring(car(frameList))
					ints = dbInstQuery(ncv ncv~>bBox)
					ppds = setof(x ints atom(x)&& x~>cellName == "ppd_1port" )
					foreach(ppd ppds
						ppd->AddLbl = "TRUE"
						ppd~>lblT1 = ""
						ppd~>lblT3 = ""
						ppd~>lblB3 = ""	
						if(lblB1 != "" then lblB1 = substring(lblB1 1 length(lblB1)-1)	)				
						ppd~>lblB1 = lblB1
						ppd~>lblB2 = lblB2	
						if(tTle != "" then tTle = substring(tTle 1 length(tTle)-1)	)							
						ppd~>tTle = tTle
						ppd~>bTle = bTle
					);;foreach
							
						
					dbSave(ncv)
					dbClose(ncv)
				);;foreach			
			);;if


			;;do infra35
			;;copy from corresponding cell without name "Infra35"	
			if(infra35_tb[cell] then
				println("Creating Infra35 RTEGs...")
				infratb = makeTable('infratb list())
				infratb["2K"] = list("195 355" "6 186" "0 191")
				infratb["3.5K"] = list("194 355" "6 186" "0 191")
				infratb["7.499K"]= list("194 355" "5 186" "0 190")
				infratb["14.999K"]= list("193 357" "3 187" "0 90 190")
				infratb["100.0K"] = list("192 358" "2 188" "0 35 165 190")
				
				foreach(infra infra35_tb[cell]
					;;infraRes = car(setof(ele infra35Res_tb[cell] car(last(parseString(infra "_"))) == strcat(ele "Infra35") ) )
					rexCompile("Infra35")
					;;infraRes = car(last(parseString(infra "_")))
					infraRes = rexReplace(infra "" 1)
					printf("Creating %s ...\n" infra )			
					
					srcCellDir = strcat(libPath  "/" infraRes )			
					dstCellDir = strcat(libPath  "/" infra)				
					cmd = strcat("cp -r " srcCellDir " " dstCellDir  )
					system(cmd)
					
					println(strcat("Updating cell " infra "..."))			
					ncv = dbOpenCellViewByType(lN infra "layout" "maskLayout" "a")	
					ints = dbInstQuery(ncv ncv~>bBox)
					
					
					;;update resonator param and rotation
					reslist = setof(aa ints atom(aa)&&pcreMatchp("^series|^shunt" aa~>cellName) )	
					ppd = car(setof(x ints atom(x)&& x~>cellName == "ppd_1port" ))
					ppdRot = ppd~>orient
					if(ppdRot == "R270" then 
						resRot = "R180"
					else
						if(ppdRot == "R0" then
							resRot = "R270"
						;else
							;error("\nppd_1port orient is not R0 or R270, please check your design.\n\n Infra35 RTEG creation failed.\n")
							;return(nil)
						);;if
					);;if
					
					;;update resonator parameters
					foreach(res reslist
						restb = list()
						resA = evalstring(res~>A)
						
						when(resA <= 2.0e3 restb = infratb["2K"])
						when(resA > 2.0e3 && resA < 3.5e3 restb = infratb["3.5K"])
						when(resA > 3.5e3 && resA < 7.499e3 restb = infratb["7.499K"])
						when(resA > 7.499e3 && resA < 14.999e3 restb = infratb["14.999K"])
						when(resA > 14.999e3 restb = infratb["100.0K"])
						

						unless(rexMatchp("q" res~>cellName)
							rexCompile("m")
							resN = rexReplace(res~>master~>cellName "q" 1)
							newlay = dbOpenCellViewByType(res~>libName resN "layout")
							res~>master = newlay
							dbClose(newlay)
						);;unless
						res~>shape = "INFRA AR3.5 "
						res~>claT = nth(0 restb)
						res~>claB = nth(1 restb)
						res~>aRel = "Yes"
						res~>arlC = nth(2 restb)
						res~>orient = resRot
						infra35AM_JY(?inst res)
					);;foreach
					
					;;remove connection and vtbs
					;vtbs = setof(x ints atom(x)&& rexMatchp("^vtb" x~>cellName ))
					;foreach(vtb vtbs dbDeleteObject(vtb))
					shps = setof(x ncv~>shapes x~>layerName == "BAW_MBE" || x~>layerName == "BAW_MTE")
					foreach(shp shps dbDeleteObject(shp))
					
					
					dbSave(ncv)
					dbClose(ncv)
				);;foreach
			
			
			);;if		 			
			dbClose(cellId)		
		);;foreach
		

        ;; add all new cells to SOS managed lib
        ;; check in for SOS prj and the cv is under managed lib
        ;; aLog=  : avoid input, -F: force check in, -sr: selected recursive 
        if(isFileName(strcat(env("PROJ_ROOT") "/" getShellEnvVar("PROJ_ID") "/cds_master/latest")) && lN == strcat(env(PROJ_ID) "_work") then
        	crtcmd = strcat("soscmd create -vk2 -aLog=  -sr  " env(PROJ_ID) "_work/" prj1 "_" prj2 "*") 
        	crt = system(crtcmd)
        	if(crt == 0 then
        		println(strcat("Creating cells with name " prj1 "_" prj2 "to SOS managed library.") )
		    	cicmd = strcat("soscmd ci -vk2 -aLog= -F -sr  " env(PROJ_ID) "_work/" prj1 "_" prj2 "*")        	
		    	ci = system(cicmd)
		    	if(ci == 0 then
		    		println(strcat("SOS checking in all cells with name " prj1 "_" prj2 ) )
		    	else
		    		println(strcat("Failed to check in all cells with with name " prj1 "_" prj2 ) )
		    	);;if
		    else
		    	println(strcat("Failed to create all cells with with name " prj1 "_" prj2 "to SOS managed library." ) )
		    );;ifcrt
        println("Done with SOS managed prj coding")
        );;if	
         	
		return("TEG Automation from Template is Done.")
	
	);;prog
);;proc



procedure( rdsBawTEGAutoUpdateTemp(cell lN cplist vartb jm4equal selay)
	prog( (var cName cNameTle ncv res resTrans resDst resType frameList frame
			i resmf restf frmmf frmtf resA ints ppds ppd Area fr )
		
		polycv = dbOpenCellViewByType(lN strcat(cell "_connect_backup") "layout")
		foreach(var vartb[cell]
			z1 = parseString(cell "_")
			cellShort = strcat(nth(0 z1) "_" nth(2 z1))
			cellShorter = strcat(nth(2 z1) "_" var)
			if(jm4equal == "MESH" then
				cName = strcat(cell "_RTEG1_" var)
				;cNameTle = cName 
				cNameTle = strcat(cellShort "_RTEG1_" var)
			else
				if(jm4equal == "JM4" then
					cName = strcat(cell "_RTEG1_" var "JM4")
					;cNameTle = strcat(cell "_RTEG1_" var)
					cNameTle = strcat(cellShort "_RTEG1_" var)
				);;if
			);;if

			ncv = dbOpenCellViewByType(lN cName "layout" "maskLayout" "a")
			
			frameList = bawHierarchyFrame(ncv 1.0 nil)
			frame = nth(2 frameList)
			frameW = evalstring(car(frameList))
		
			;;copy resonator
			res = car( setof(x cplist rexMatchp(var x~>name)) )			
			;resTrans = list( -car(res~>xy)  -cadr(res~>xy) )
			;resDst = dbCopyFig(res ncv list(resTrans "R0" 1.0) )
			resDst = dbCopyFig(res ncv list(list(-frameW 0) "R0" 1.0) )
			
			
			;;copy vtb and remove those not attach to resonator
			vtbs = setof(x cplist rexMatchp("^vtb" x~>cellName))
			vtbcps = list()
			foreach(vtb vtbs 
				vtbcp = dbCopyFig(vtb ncv list( list(-frameW 0) "R0" 1.0)) 
				vtbcps = append1(vtbcps vtbcp)
			);;foreach
			
		
			resbbx = resDst~>bBox
			bbx = list(leftEdge(resbbx)-10.0:bottomEdge(resbbx)-10.0  rightEdge(resbbx)+10.0:topEdge(resbbx)+10.0)

			overlaps = dbGetTrueOverlaps(ncv bbx)
			overs = list()
			foreach(x overlaps if(x~>cellName then overs = append1(overs x)))
	
			vtbovers = setof(x overs atom(x) && rexMatchp("^vtb" x~>cellName))

			;;vtbs = setof(x ncv~>instances rexMatchp("^vtb" x~>cellName))
			foreach(vtb vtbcps if(!member(vtb vtbovers) then dbDeleteObject(vtb)) )		
			
						
			;;copy polygons and remove those not attach to resonator
			if(polycv then
				polyOvers = dbGetTrueOverlaps(polycv res~>bBox)
				foreach(poly polyOvers dbCopyFig(poly ncv list( list(-frameW 0) "R0" 1.0)) )
						
			else
				println(strcat("There's no " cell "_connect_backup cell in the library. No polygon(s) get copied."))
			);;if  

			if(rexMatchp("^series" resDst~>cellName) then 
				resType = "series"
			else
				if(pcreMatchp("^shunt|^mimcap" resDst~>cellName)  then 
					resType = "shunt"
				);;if
			);;if
			
			
			;;update frame TF/MF, 
			;;if resonator TFx = t--> fully covered, else NoTFx, 
			;;series-->TFP fully covered NoTFS,  shunt->TFS fully covered NoTFP
			;frameList = bawHierarchyFrame(ncv 1.0 nil)
			;frame = nth(2 frameList)
			trimList = list(list("TEG" "boolean" t))
			tfChk = nil		
			frmTFGrp = ""				
			for(i 1 8
				if(rexMatchp("^mimcap" resDst~>cellName) then
					frmValue = "Transparant"	
					frmmf = strcat("MF" sprintf(nil "%d" i) )
					trimList = append1(trimList list(frmmf "string" frmValue))	
					frmtf = strcat("TF" sprintf(nil "%d" i) )
					trimList = append1(trimList list(frmmf "string" frmValue))	
					frmTFGrp = ""
				else
					resmf = dbFindProp(resDst strcat("MF" sprintf(nil "%d" i) "_Trim") )~>value	
					restf = dbFindProp(resDst strcat("TF" sprintf(nil "%d" i) "_Trim") )~>value
					frmmf = strcat("MF" sprintf(nil "%d" i) )
					if(resmf == "TRUE" then 
						frmValue = "Fully_Covered"					
					else	
						frmValue = strcat("No_" frmmf)	
					);;if				
					trimList = append1(trimList list(frmmf "string" frmValue))	
					
					frmtf = strcat("TF" sprintf(nil "%d" i) )			
					if(restf == "TRUE" then 	
						frmValue = "Fully_Covered"	
					else
						frmValue = strcat("No_" frmtf)		
						if(!tfChk then frmTFGrp = sprintf(nil "TF%d" i) tfChk = t)
					);;if
					trimList = append1(trimList list(frmtf "string" frmValue))		
				);;if
			);;for			
			if(resType == "series" then 
				trimList = append(trimList list( list("TFS" "string" "No_TFS") list("TFP" "string" "Fully_Covered"))  )
			else
				trimList = append(trimList list( list("TFS" "string" "Fully_Covered") list("TFP" "string" "No_TFP"))  )
			);;if
			dbReplacePropList(frame trimList)
			
					
		
			;;swithc cell master to series/shunt v3
			;;update release hole, cutline angle = 90, cutline spacing = 14.0 for JM4
			;;0K – 7.49K  90 270, 7.5K – 14.99K  5 130 235, 15K – 30K 45 140 225 315
			if(jm4equal == "JM4" then			
				resDst~>master = selay 				
				resDst~>spm = "14.0"
				resDst~>cla = "90.0"
				resDst~>rot = "0.0"
				resDst~>claT = "100 260"
				resDst~>claB = "280 80"
				resDst~>orient = "R270"
				resA = evalstring(resDst~>A)

				if(resA< 7.49e3 then
					resDst~>arlC = "90 270" 	
				else
					if(resA>=7.49e3 && resA < 14.99e3 then
						resDst~>arlC = "5 130 235" 
					else
						if(resA >= 14.99e3	then
							resDst~>arlC = "45 140 225 315"
						)
					)
				);;if	
				dbDeletePropByName(resDst "SharpPts") 
				dbDeletePropByName(resDst "SharpR")
				dbDeletePropByName(resDst "vtbfc" )	
				rdsBawTriggerCallbacksCV(ncv)	
			);;if	


			;;update ppd labels
			ints = dbInstQuery(ncv ncv~>bBox)
			ppds = setof(x ints atom(x)&& x~>cellName == "ppd_1port" )

			foreach(ppd ppds
				ppd->AddLbl = "TRUE"

/*				if(rexMatchp("^mimcap" resDst~>cellName) then
					ppd->blbT1 = "CAP"
				else
					if(rexMatchp("^series[0-9]" resDst~>cellName) || rexMatchp("^shunt[0-9]" resDst~>cellName) then
						ppd~>lblT1 = "JM4"
					else
						ppd~>lblT1 = "MESH"
					);;if
				);;if

				unless(rexMatchp("^mimcap" resDst~>cellName)
					;;sprintf(Area "%A" round(evalstring(resDst~>A)*1000)/1000/1000.0)
					sprintf(Area "%.3f" evalstring(resDst~>A)/1000.0)
					Area = strcat(Area "K")
					ppd~>lblT3 = strcat("A=" Area)
					sprintf(fr "%A" evalstring(aelEngNotation(resDst~>Fs))/1e6 )
		        	fr = strcat(fr "M")
		        	if(evalstring(resDst~>ORaW) == -99 then
		        		ppd~>lblB1 = "ORaW=NA"
		        	else
						ppd~>lblB1 = strcat("ORaW=" resDst~>ORaW)
					);;if
					if(evalstring(resDst~>ReW) == -99 then
		        		ppd~>lblB2 = "ReW=NA"
		        	else
						ppd~>lblB2 = strcat("ReW=" resDst~>ReW)
					);;if
					if(evalstring(resDst~>MRaW) == -99 then
		        		ppd~>lblB3 = "MRaW=NA"
		        	else
						ppd~>lblB3 = strcat("MRaW=" resDst~>MRaW)
					);;if
					ppd~>tTle = cNameTle
					ppd~>bTle = strcat( upperCase(resType) "      FREQ=" fr)
					ppd~>ResonatorType = resType
				);;unless	
*/

	;;03/15/2024, v0.17 updated per Brian's request	
					frmw = evalstring(nth(0 frameList))
					frml = evalstring(nth(1 frameList))
					frmMin = apply('min list(frmw frml))	
					if(frmMin <= 528 then
						ppd~>lblT1 = ""
						ppd~>lblT3 = ""
						ppd~>lblB1 = cellShorter
						if(rexMatchp("^mimcap" resDst~>cellName) then
							ppd->lblB2 = "CAP"
						else
							ppd~>lblB2 = frmTFGrp							
						)
						ppd~>lblB3 = ""
						ppd~>tTle = ""
						ppd~>bTle = ""	
					else					
						ppd~>lblT1 = ""
						ppd~>lblT3 = ""
						ppd~>lblB1 = ""
						ppd~>lblB2 = ""
						ppd~>lblB3 = ""
						ppd~>tTle = cNameTle
						if(rexMatchp("^mimcap" resDst~>cellName) then
							ppd->bTle = "CAP"
						else
							ppd~>bTle = strcat("FREQ=" frmTFGrp)	
						);;if	
					);;if				
			);;foreach			

			
			printf("Creating %s ...\n" cName )			
			dbSave(ncv)
			dbClose(ncv)
			
			
			
		);;foreach	

		dbClose(polycv)
	);;prog
);;proc


procedure( rdsBawCopyCellsCshV2(cshFile dir cpCellList nameVarList)
	let( (myfile srcCellDir dstCellDir)
		myfile = outfile(cshFile)
		fprintf(myfile "#!/bin/csh\n" )	
		;;comBat = strcat(dir "/*_W*_B*")
		;;fprintf(myfile "rm -rf %s\n" comBat )			
		dstCellList = list()	
		foreach(cell cpCellList
			srcCellDir = strcat(dir "/" cell )
			foreach(var nameVarList				
				dstCellDir = strcat(dir "/" var)
				fprintf(myfile "if ( -d %s ) then  \nrm -rf %s \nendif \n" dstCellDir dstCellDir)
				fprintf(myfile "cp -r %s  %s\n" srcCellDir dstCellDir )
			);;foreachvar
		);;foreachcell
		close(myfile)
		
		cmd1 = strcat("chmod 755 " cshFile)
		
		system(cmd1)
		;;println(cmd1)
		system(cshFile)		
		println(cshFile)
	);;let
);;proc


procedure(infra35AM_JY(@key (inst css()))
	let( (shapeArea)
		shapeArea = atoi(inst~>A)
		cond(
			( shapeArea <= 2000
				inst~>rot = "0"
				inst~>claT = "195 355"
				inst~>claB = "6 186"
				inst~>arlC = "0 191")
			( shapeArea > 2000 && shapeArea <= 3500
				inst~>rot = "0"
				inst~>claT = "194 355"
				inst~>claB = "6 186"
				inst~>arlC = "0 191")
			( shapeArea > 3500 && shapeArea <= 7500
				inst~>rot = "0"
				inst~>claT = "194 355"
				inst~>claB = "5 186"
				inst~>arlC = "0 190")
			( shapeArea > 7500 && shapeArea <= 15000
				inst~>rot = "0"
				inst~>claT = "193 357"
				inst~>claB = "3 187"
				inst~>arlC = "0 90 190")
			( shapeArea > 15000
				inst~>rot = "0"
				inst~>claT = "192 358"
				inst~>claB = "3 187"
				inst~>arlC = "0 35 165 190")
		)
		printf("area: %s\n" inst~>A)
	)
)
